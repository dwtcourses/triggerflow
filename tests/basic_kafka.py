from eventprocessor_client import CloudEventProcessorClient, CloudEvent, DefaultActions
from eventprocessor_client.utils import load_config_yaml
from eventprocessor_client.sources.interfaces.kafka import KafkaCloudEventSource

if __name__ == "__main__":
    client_config = load_config_yaml('~/client_config.yaml')
    kafka_config = client_config['event_sources']['kafka']

    er = CloudEventProcessorClient(**client_config['event_processor'])

    kafka = KafkaCloudEventSource(name='my_kafka_eventsource',
                                  broker_list=kafka_config['broker_list'],
                                  topic='hello')

    er.create_namespace(namespace='basic_kafka', global_context=client_config['global_context'], event_source=kafka)

    # init__ >> ca1 >> [map1, ca2] >> map2 >> ca3 >> end__

    url = 'https://us-east.functions.cloud.ibm.com/api/v1/namespaces/cloudlab_urv_us_east/actions/eventprocessor_functions/kafka_test'

    er.add_trigger(CloudEvent('init__'),
                   action=DefaultActions.IBM_CF_INVOKE_KAFKA,
                   context={'subject': 'ca1',
                            'function_args': {'iter': 1},
                            'function_url': url,
                            'kind': 'callasync'})

    # er.add_trigger(CloudEvent('ca1'),
    #                condition=DefaultConditions.IBM_CF_JOIN,
    #                action=DefaultActions.IBM_CF_INVOKE_KAFKA,
    #                context={'subject': 'map1',
    #                         'function_args': [{'iter': x} for x in range(3)],
    #                         'function_url': url,
    #                         'kind': 'map'})
    #
    # er.add_trigger(CloudEvent('ca1'),
    #                condition=DefaultConditions.IBM_CF_JOIN,
    #                action=DefaultActions.IBM_CF_INVOKE_KAFKA,
    #                context={'subject': 'ca2',
    #                         'function_args': {'iter': 1},
    #                         'function_url': url,
    #                         'kind': 'callasync'})
    #
    # er.add_trigger([CloudEvent('map1'), CloudEvent('ca2')],
    #                condition=DefaultConditions.IBM_CF_JOIN,
    #                action=DefaultActions.IBM_CF_INVOKE_KAFKA,
    #                context={'subject': 'map2',
    #                         'function_args': [{'iter': x} for x in range(3)],
    #                         'function_url': url,
    #                         'kind': 'map'})
    #
    # er.add_trigger(CloudEvent('map2'),
    #                condition=DefaultConditions.IBM_CF_JOIN,
    #                action=DefaultActions.IBM_CF_INVOKE_KAFKA,
    #                context={'subject': 'ca3',
    #                         'function_args': {'iter': 1},
    #                         'function_url': url,
    #                         'kind': 'callasync'})
    #
    # er.add_trigger(CloudEvent('ca3'),
    #                condition=DefaultConditions.IBM_CF_JOIN,
    #                action=DefaultActions.TERMINATE)
