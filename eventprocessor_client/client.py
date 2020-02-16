import uuid

import requests
import re
from requests.auth import HTTPBasicAuth
from typing import Optional, Union, List

import eventprocessor_client.exceptions
from .sources.model import CloudEventSource
from .sources.cloudevent import CloudEvent
from .conditions_actions import ConditionActionModel, DefaultActions, DefaultConditions


# TODO Replace prints with proper logging

class CloudEventProcessorClient:
    def __init__(self,
                 api_endpoint: str,
                 user: str,
                 password: str,
                 namespace: Optional[str] = None,
                 eventsource_name: Optional[str] = None,
                 caching: Optional[bool] = False):
        """
        Initializes CloudEventProcessor client.
        :param api_endpoint: Endpoint of the Event Processor API.
        :param user: Username to authenticate this client towards the API REST.
        :param password: Password to authenticate this client towards the API REST.
        :param namespace: Namespace which this client targets by default when managing triggers.
        :param eventsource_name: Eventsource which this client targets by default when managing triggers.
        :param caching: Add triggers to local cache, to then commit cached
                        triggers in a single request using push_triggers().
        """
        self.eventsource_name = eventsource_name
        self.api_endpoint = api_endpoint
        self.caching = caching
        self.__namespace = namespace
        self.__trigger_cache = {}

        if not re.fullmatch(r"[a-zA-Z0-9_]+", user):
            raise ValueError('Invalid Username')
        if not re.fullmatch(r"^(?=.*[A-Za-z])[A-Za-z\d@$!%*#?&]+$", password):
            raise ValueError('Invalid Password')

        self.__basic_auth = HTTPBasicAuth(user, password)

    def target_namespace(self, namespace: str):
        """
        Sets the target namespace of this client.
        :param namespace: Namespace name.
        """
        self.__namespace = namespace

    def create_namespace(self, namespace: Optional[str] = None,
                         global_context: Optional[dict] = None,
                         event_source: Optional[CloudEventSource] = None):
        """
        Creates a namespace.
        :param namespace: Namespace name.
        :param global_context: Read-only key-value state that is visible for all triggers in the namespace.
        :param event_source: Applies this event source to the new namespace.
        """
        default_context = {'namespace': namespace}

        if namespace is None and self.__namespace is None:
            raise ValueError('Namespace cannot be None')
        elif namespace is None:
            namespace = self.__namespace

        self.__namespace = namespace

        if global_context is not None and type(global_context) is dict:
            global_context.update(default_context)
        elif global_context is not None and type(global_context) is not dict:
            raise Exception('Global context must be json-serializable dict')
        else:
            global_context = {}

        evt_src = event_source.json if event_source is not None else None

        res = requests.put('/'.join([self.api_endpoint, 'namespace', namespace]),
                           auth=self.__basic_auth,
                           json={'global_context': global_context,
                                 'event_source': evt_src})

        print("{}: {}".format(res.status_code, res.json()))
        if res.ok:
            return res.json()
        elif res.status_code == 409:
            raise eventprocessor_client.exceptions.ResourceAlreadyExistsError(res.json())
        else:
            raise Exception(res.json())

    def delete_namespace(self, namespace: str = None):
        if namespace is None and self.__namespace is None:
            raise eventprocessor_client.exceptions.NullNamespaceError()
        elif namespace is None:
            namespace = self.__namespace

        res = requests.delete('/'.join([self.api_endpoint, 'namespace', namespace]),
                              auth=self.__basic_auth,
                              json={})

        print("{}: {}".format(res.status_code, res.json()))
        if res.ok:
            return res.json()
        elif res.status_code == 409:
            raise eventprocessor_client.exceptions.ResourceDoesNotExist(res.json())
        else:
            raise Exception(res.json())

    def set_event_source(self, eventsource_name: str):
        """
        Sets the default event source for this client when managing triggers.
        :param eventsource_name: Event source name.
        """
        self.eventsource_name = eventsource_name

    def add_event_source(self, eventsource: CloudEventSource, overwrite: Optional[bool] = False):
        """
        Adds an event source to the target namespace.
        :param eventsource: Instance of CloudEventSource containing the specifications of the event source.
        :param overwrite: True for overwriting the event source specification.
        """

        res = requests.put('/'.join([self.api_endpoint, 'namespace', self.__namespace, 'eventsource', eventsource.name]),
                           params={'overwrite': overwrite},
                           auth=self.__basic_auth,
                           json={'eventsource': eventsource.json})

        print("{}: {}".format(res.status_code, res.json()))
        if res.ok:
            return res.json()
        elif res.status_code == 409:
            raise eventprocessor_client.exceptions.ResourceAlreadyExistsError(res.json())
        else:
            raise Exception(res.json())

    def add_trigger(self,
                    event: Union[CloudEvent, List[CloudEvent]],
                    condition: Optional[ConditionActionModel] = DefaultConditions.TRUE,
                    action: Optional[ConditionActionModel] = DefaultActions.PASS,
                    context: Optional[dict] = None,
                    transient: Optional[bool] = True,
                    trigger_id: Optional[str] = None):
        """
        Adds a trigger to the target namespace.
        :param event: Instance of CloudEvent, this CloudEvent's subject and type will fire this trigger.
        :param condition: Callable that is executed every time the event is received. If it returns true,
        then Action is executed. It has to satisfy signature contract (context, event).
        :param action: Action to perform when event is received and condition is True. It has to satisfy signature
        contract (context, event).
        :param context: Trigger key-value state, only visible for this specific trigger.
        :param transient: If true, this trigger is deleted after action is executed.
        :param trigger_id: Custom ID for a persistent trigger.
        """
        if self.__namespace is None:
            raise eventprocessor_client.exceptions.NullNamespaceError()

        if transient and trigger_id is not None:
            raise eventprocessor_client.exceptions.NamedTransientTriggerError()

        # Check for arguments types
        if context is None:
            context = {}
        if type(context) is not dict:
            raise Exception('Context must be an json-serializable dict')

        events = [event] if type(event) is not list else event
        events = list(map(lambda evt: evt.json, events))
        trigger = {
            'condition': condition.value,
            'action': action.value,
            'context': context,
            'depends_on_events': events,
            'transient': transient,
            'trigger_id': trigger_id}

        if self.caching:
            res = self.__add_trigger_cache(trigger)
        else:
            res = self.__add_trigger_remote(trigger)

        return res

    def delete_trigger(self, trigger_id: str):
        if self.caching:
            res = self.__delete_trigger_cache(trigger_id)
        else:
            res = self.__delete_trigger_remote(trigger_id)
        return res

    def get_trigger(self, trigger_id: str):
        if self.caching:
            res = self.__get_trigger_cache(trigger_id)
        else:
            res = self.__get_trigger_remote(trigger_id)
        return res

    def amend_trigger(self, trigger_id: str, trigger: dict):
        if self.caching:
            res = self.__amend_trigger_cache(trigger_id)
        else:
            res = self.__amend_trigger_remote(trigger_id)
        return res

    def commit_cached_triggers(self):
        """
        Commit cached triggers to database.
        :return:
        """
        if not self.caching:
            raise Exception('No trigger caching is being used')
        if self.__trigger_cache:
            res = self.__add_trigger_remote(list(self.__trigger_cache.values()))
            return res
        else:
            raise Exception('Trigger cache empty')

    def list_cached_triggers(self):
        """
        List cached triggers.
        :return: dict Trigger cache
        """
        if not self.caching:
            raise Exception('No trigger caching is being used')

        return self.__trigger_cache

    def flush_cached_triggers(self):
        """
        Discard cached triggers.
        """
        self.__trigger_cache = {}

    def __add_trigger_cache(self, trigger):
        if trigger['trigger_id'] is None:
            trigger['trigger_id'] = str(uuid.uuid4())
        elif trigger['trigger_id'] in self.__trigger_cache:
            raise Exception('Trigger {} already exists'.format(trigger['trigger_id']))
        else:
            self.__trigger_cache[trigger['trigger_id']] = trigger

        print({'trigger': trigger['trigger_id']})
        return {'trigger': trigger['trigger_id']}

    def __add_trigger_remote(self, trigger):
        triggers = [trigger] if type(trigger) != list else trigger

        res = requests.post('/'.join([self.api_endpoint, 'namespace', self.__namespace, 'trigger']),
                            auth=self.__basic_auth,
                            json={'triggers': triggers})

        print('{}: {}'.format(res.status_code, res.json()))
        if not res.ok:
            raise Exception(res.json())
        else:
            return res.json()

    def __delete_trigger_cache(self, trigger_id):
        if trigger_id in self.__trigger_cache:
            del self.__trigger_cache[trigger_id]
        else:
            raise TypeError('Trigger {} does not exist'.format(trigger_id))

    def __delete_trigger_remote(self, trigger_id):
        raise NotImplementedError()

    def __get_trigger_cache(self, trigger_id):
        if trigger_id in self.__trigger_cache:
            return {'trigger': self.__trigger_cache[trigger_id].copy()}
        else:
            raise TypeError('Trigger {} does not exist'.format(trigger_id))

    def __get_trigger_remote(self, trigger_id):
        raise NotImplementedError()

    def __amend_trigger_cache(self, trigger_id, trigger):
        if trigger_id in self.__trigger_cache:
            self.__trigger_cache[trigger_id] = trigger.copy()
        else:
            raise TypeError('Trigger {} does not exist'.format(trigger_id))

    def __amend_trigger_remote(self, trigger_id, trigger):
        pass
