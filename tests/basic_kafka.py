from triggerflow.client import TriggerflowClient, CloudEvent, DefaultActions
from triggerflow.client.utils import load_config_yaml
from triggerflow.client.sources import KafkaEventSource

if __name__ == "__main__":
    client_config = load_config_yaml('~/client_config.yaml')

    tf = TriggerflowClient(**client_config['triggerflow'])

    kafka = KafkaEventSource(broker_list=client_config['kafka']['broker_list'])

    tf.create_workspace(workspace='basic_kafka', global_context={'ibm_cf': client_config['ibm_cf']}, event_source=kafka)

    # init__ >> ca1 >> [map1, ca2] >> map2 >> ca3 >> end__

    url = 'https://us-east.functions.cloud.ibm.com/api/v1/namespaces/cloudlab_urv_us_east/actions/eventprocessor_functions/kafka_test'

    tf.add_trigger(event=CloudEvent('init__'),
                   action=DefaultActions.IBM_CF_INVOKE_KAFKA,
                   context={'subject': 'ca1',
                            'function_args': {'iter': 1},
                            'function_url': url,
                            'kind': 'callasync'})
