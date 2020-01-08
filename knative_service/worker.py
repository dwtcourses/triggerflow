"""Service class, CanaryDocumentGenerator class.

/*
 * Licensed to the Apache Software Foundation (ASF) under one or more
 * contributor license agreements.  See the NOTICE file distributed with
 * this work for additional information regarding copyright ownership.
 * The ASF licenses this file to You under the Apache License, Version 2.0
 * (the "License"); you may not use this file except in compliance with
 * the License.  You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
"""
import json
import logging
from importlib import import_module
from uuid import uuid4
from enum import Enum
from datetime import datetime
from multiprocessing import Process
import brokers as brokers
from datetimeutils import seconds_since
from libs.cloudant_client import CloudantClient


class AuthHandlerException(Exception):
    def __init__(self, response):
        self.response = response


class Worker(Process):
    class State(Enum):
        INITIALIZED = 'Initialized'
        RUNNING = 'Running'
        FINISHED = 'Finished'

    def __init__(self, namespace, private_credentials, user_credentials):
        super().__init__()

        self.worker_status = {}
        self.namespace = namespace
        self.worker_id = str(uuid4())
        self.__private_credentials = private_credentials
        self.__user_credentials = user_credentials

        self.triggers = {}
        self.source_events = {}
        self.global_context = {}
        self.events = {}

        # Instantiate DB client
        self.__cloudant_client = CloudantClient(self.__private_credentials['cloudant']['username'],
                                                self.__private_credentials['cloudant']['apikey'])

        # Get global context
        dc = self.__cloudant_client.get(database_name=namespace, document_id='global_context')
        self.global_context.update(dc)

        self.current_state = Worker.State.INITIALIZED

    def run(self):
        logging.info('[{}] Starting worker {}'.format(self.namespace, self.worker_id))
        worker_start_time = datetime.now()
        self.current_state = Worker.State.RUNNING
        self.__update_triggers()

        # Instantiate broker client
        event_source = self.__cloudant_client.get(database_name=self.namespace, document_id='event_source')
        event_source_type = event_source['event_source_type']
        broker = getattr(brokers, '{}Broker'.format(event_source_type))
        config = event_source[event_source_type]
        broker = broker(**config)

        while self.__should_run():
            record = broker.poll()
            if record:
                event = json.loads(record.value())
                print('New Event-->', event)
                subject = event['subject']

                if subject in self.events:
                    self.events[subject].append(event)
                else:
                    self.events[subject] = [event]

                if subject in self.source_events:
                    triggers = self.source_events[subject]

                    for trigger_id in triggers:
                        condition_name = self.triggers[trigger_id]['condition']
                        action_name = self.triggers[trigger_id]['action']
                        context = self.triggers[trigger_id]['context']

                        context.update(self.global_context)
                        context.update(event_source)
                        context['events'] = self.events
                        context['source_events'] = self.source_events
                        context['triggers'] = self.triggers
                        context['trigger_id'] = trigger_id
                        context['depends_on_events'] = self.triggers[trigger_id]['depends_on_events']

                        mod = import_module('conditions', 'default')
                        condition = getattr(mod, '_'.join(['condition', condition_name.lower()]))
                        mod = import_module('actions', 'default')
                        action = getattr(mod, '_'.join(['action', action_name.lower()]))

                        try:
                            if condition(context, event):
                                action(context, event)
                        except Exception as e:
                            # TODO Handle condition/action exceptions
                            raise e
                else:
                    logging.warn('[{}] Received unexpected event: {} '.format(self.namespace, subject))

                broker.commit([record])

        self.worker_status['worker_start_time'] = str(worker_start_time)
        self.worker_status['worker_end_time'] = str(datetime.now())
        self.worker_status['worker_elapsed_time'] = seconds_since(worker_start_time)
        self.__cloudant_client.put(database_name=self.namespace,
                                   document_id='worker_{}'.format(self.worker_id), data=self.worker_status)
        logging.info('[{}] Worker {} finished - {} seconds'.format(self.namespace, self.worker_id,
                                                                   self.worker_status['worker_elapsed_time']))
        print('--------------- WORKER FINISHED ---------------')

    def __should_run(self):
        return self.current_state == Worker.State.RUNNING

    def __update_triggers(self):
        try:
            self.source_events = self.__cloudant_client.get(database_name=self.namespace, document_id='source_events')
            new_triggers = self.__cloudant_client.get(database_name=self.namespace, document_id='triggers')
            for k, v in new_triggers.items():
                if k not in self.triggers:
                    self.triggers[k] = v
            return True
        except KeyError:
            logging.error('Could not retrieve triggers and/or source events for {}'.format(self.namespace))
            return None

    @staticmethod
    def __dump_request_response(trigger_name, response):
        response_dump = {
            'request': {
                'method': response.request.method,
                'url': response.request.url,
                'path_url': response.request.path_url,
                'headers': response.request.headers,
                'body': response.request.body
            },
            'response': {
                'status_code': response.status_code,
                'ok': response.ok,
                'reason': response.reason,
                'url': response.url,
                'headers': response.headers,
                'content': response.content
            }
        }

        logging.error('[{}] Dumping the content of the request and response:\n{}'.format(trigger_name, response_dump))
