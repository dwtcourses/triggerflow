from uuid import uuid4
from importlib import import_module

from eventprocessor_client.utils import load_config_yaml
from eventprocessor_client.client import CloudEventProcessorClient, CloudEvent, DefaultActions, DefaultConditions
from asf.conditions_actions import AwsAsfActions, AwsAsfConditions

ep = None
sm_count = 0


def asf2triggers(asf_json):
    global ep, sm_count
    # run_id = '_'.join(['asf_state-machine', str(uuid4())])
    run_id = 'asf_test'
    ep_config = load_config_yaml('~/client_config.yaml')
    # asf_config = load_config_yaml('~/asf_config.yaml')

    # evt_src_type = asf_config['event_source']
    # evt_src_config = asf_config['event_sources'][evt_src_type]
    # evt_src_class = asf_config['event_sources'][evt_src_type]['class']
    # del evt_src_config['class']

    # mod = import_module('eventprocessor_client.sources')
    # evt_src = getattr(mod, '{}CloudEventSource'.format(evt_src_class))
    # event_source = evt_src(name=run_id,
    #                        topic=run_id,
    #                        **evt_src_config)

    ep = CloudEventProcessorClient(api_endpoint=ep_config['event_processor']['api_endpoint'],
                                   user=ep_config['event_processor']['user'],
                                   password=ep_config['event_processor']['password'],
                                   namespace=run_id,
                                   eventsource_name=run_id,
                                   caching=True)

    # ep.create_namespace(run_id, event_source=event_source)

    state_machine(asf_json, '$init')
    with open('trg.json', 'w') as f:
        f.write(json.dumps(ep.list_cached_triggers(), indent=2))

    # ep.commit_cached_triggers()


def state_machine(asf_json, init_event):
    global ep, sm_count
    sm_id = 'StateMachine{}'.format(sm_count)
    sm_count += 1
    upstream_relatives = {}
    final_states = []
    choices = {}

    for state_name, state in asf_json['States'].items():
        if 'End' in state and state['End']:
            final_states.append(state_name)
        elif 'Next' in state:
            upstream_relatives[state['Next']] = state_name
        elif state['Type'] == 'Choice':
            for choice in state['Choices']:
                upstream_relatives[choice['Next']] = state_name

    upstream_relatives[asf_json['StartAt']] = init_event

    for state_name, state in asf_json['States'].items():
        context = {'subject': state_name, 'State': state.copy()}
        if state_name in choices:
            context['Condition'] = choices[state_name].copy()
        if state['Type'] == 'Pass':
            ep.add_trigger(CloudEvent(upstream_relatives[state_name]),
                           condition=AwsAsfConditions.AWS_ASF_CONDITION,
                           action=AwsAsfActions.AWS_ASF_PASS,
                           context=context,
                           trigger_id=state_name,
                           transient=False)
        elif state['Type'] == 'Task':
            ep.add_trigger(CloudEvent(upstream_relatives[state_name]),
                           condition=AwsAsfConditions.AWS_ASF_CONDITION,
                           action=AwsAsfActions.AWS_ASF_TASK,
                           context=context,
                           trigger_id=state_name,
                           transient=False)
        elif state['Type'] == 'Choice':
            choices = {}
            for choice in state['Choices']:
                upstream_relatives[choice['Next']] = upstream_relatives[state_name]
                choices[choice['Next']] = choice.copy()
        elif state['Type'] == 'Parallel':
            sub_state_machines = []
            for branch in state['Branches']:
                sub_sm_id = state_machine(branch, upstream_relatives[state_name])
                sub_state_machines.append(sub_sm_id)
            ep.add_trigger([CloudEvent(sub_state_machine_id) for sub_state_machine_id in sub_state_machines],
                           condition=AwsAsfConditions.AWS_ASF_CONDITION,
                           action=AwsAsfActions.AWS_ASF_PASS,
                           context=context,
                           trigger_id=state_name,
                           transient=False)
        elif state['Type'] == 'Wait':
            ep.add_trigger(CloudEvent(upstream_relatives[state_name]),
                           condition=AwsAsfConditions.AWS_ASF_CONDITION,
                           action=AwsAsfActions.AWS_ASF_TASK,
                           context=context,
                           trigger_id=state_name,
                           transient=False)
        elif state['Type'] == 'Map':
            ep.add_trigger(CloudEvent(upstream_relatives[state_name]),
                           condition=AwsAsfConditions.AWS_ASF_CONDITION,
                           action=AwsAsfActions.AWS_ASF_TASK,
                           context=context,
                           trigger_id=state_name,
                           transient=False)
            iterator = state_machine(state['Iterator'], state_name)
            upstream_relatives[state['Next']] = iterator
        elif state['Type'] == 'Succeed':
            raise NotImplementedError()
        elif state['Type'] == 'Fail':
            raise NotImplementedError()

    ep.add_trigger([CloudEvent(final_state) for final_state in final_states],
                   condition=AwsAsfConditions.AWS_ASF_CONDITION,
                   action=AwsAsfActions.AWS_ASF_END_STATEMACHINE,
                   context={'subject': sm_id},
                   trigger_id=sm_id,
                   transient=False)

    return sm_id


my_statemachine = """
{
  "Comment": "Parallel Example.",
  "StartAt": "SetupParameters",
  "States": {
    "SetupParameters": {
      "Type": "Pass",
      "Result": 2,
      "ResultPath": "$.my_number",
      "Next": "Parallel"
    },
    "Parallel": {
      "Type": "Parallel",
      "End": true,
      "Branches": [
        {
          "StartAt": "Map",
          "States": {
            "Map": {
              "Type": "Map",
              "Iterator": {
                "StartAt": "MapBranch",
                "States": {
                  "MapBranch": {
                    "Type": "Parallel",
                    "Branches": [
                      {
                        "StartAt": "MapParallelBranch1-1",
                        "States": {
                          "MapParallelBranch1-1": {
                            "Type": "Pass",
                            "Next": "MapParallelBranch1-2"
                          },
                          "MapParallelBranch1-2": {
                            "Type": "Pass",
                            "End": true
                          }
                        }
                      },
                      {
                        "StartAt": "MapParallelBranch2",
                        "States": {
                          "MapParallelBranch2": {
                            "Type": "Pass",
                            "End": true
                          }
                        }
                      }
                    ],
                    "End": true
                  }
                }
              },
              "Next": "Reduce"
            },
            "Reduce": {
              "Type": "Pass",
              "End": true
            }
          }
        },
        {
          "StartAt": "Branching",
          "States": {
            "Branching": {
              "Type": "Choice",
              "Choices": [
                {
                  "Variable": "$.my_number",
                  "NumericEquals": 1,
                  "Next": "Result1"
                },
                {
                  "Variable": "$.my_number",
                  "NumericEquals": 2,
                  "Next": "Result2"
                }
              ]
            },
            "Result1": {
              "Type": "Pass",
              "End": true
            },
            "Result2": {
              "Type": "Pass",
              "End": true
            }
          }
        }
      ]
    }
  }
}
"""

import json

asf2triggers(json.loads(my_statemachine))
