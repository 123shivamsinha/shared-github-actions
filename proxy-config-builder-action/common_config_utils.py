
'''
Created on Nov 18, 2022

@author: y680550
'''

import json
import traceback
import yaml
from regex_gen import regex_for_range


def yaml_loader(filepath):
    try:
        with open(filepath, "r") as fp:
            data = yaml.safe_load(fp)
    except Exception as e:
        return None
    return data


def json_loader(filepath):
    try:
        with open(filepath, "r") as fp:
            data = json.load(fp)
    except Exception as e:
        return None
    return data


def xml_loader(filepath):
    try:
        with open(filepath, "r") as fp:
            data = fp.read()
    except Exception as e:
        return None
    return data


def load_file(filepath):
    if filepath.lower().endswith(".json"):
        data = json_loader(filepath)
    elif filepath.lower().endswith(".yaml"):
        data = yaml_loader(filepath)
    elif filepath.lower().endswith(".yml"):
        data = yaml_loader(filepath)
    elif filepath.lower().endswith(".xml"):
        data = xml_loader(filepath)
    else:
        raise ValueError("file on the path is not in the correct format")
    return data


def value_from_json_field(data, field):
    return data.get(field)


def value_from_json_path(data, path):
    for field in path.split('.'):
        if isinstance(data.get(field), dict):
            data = data.get(field)
        elif isinstance(data.get(field), list):
            data = data.get(field)
        else:
            return data.get(field)
    return data


def replace_placeholder(data, placeholder_name, placeholder_value):
    final = None
    data_ = None
    try:
        data_ = json.dumps(data)
        if placeholder_value != None:
            final = json.loads(data_.replace(placeholder_name, placeholder_value))
        else:
            final = json.loads(data_.replace(placeholder_name, ''))
    except Exception as e:
        traceback.print_exc()
        raise ValueError("placeholder_name ", placeholder_name, "placeholder_value ", placeholder_value)
    return final


def remove_unneeded_braces(regx_str):
    left = ''
    right = ''
    if regx_str.__contains__('('):
        right = regx_str.split('(')[1]
        if right.__contains__(')'):
                left = right.split(')')[0]
    if len(left) == 1:
        return left
    else:
        return regx_str


def convert_rtlbl_in_regx(data, env, service_default_version):
    default_value = None
    data_ = None
    upper = None
    env_regx_map = {}
    regex_dict = {}
    if data is None:
        default_value = service_default_version
    elif data.get('default') != None:
        data_ = data.get(env)
        default_value = data.get('default')
        if data_ != None and data_.get('default') != None:
            default_value = data_.get('default')
            data_.pop('default')
    else:
        default_value = service_default_version
    if data_ != None:
        no_of_rtlabels = len(data_.keys())
        if no_of_rtlabels > 1:
            for rtlbl in sorted(data_.keys()):
                regx_str = ''
                
                # code by Saurabh
                all_rtlabels = sorted(data_.keys())
                position_of_rtlabel = all_rtlabels.index(rtlbl)
                
                if position_of_rtlabel + 1 < len(all_rtlabels):
                    next_rtlabel = all_rtlabels[position_of_rtlabel + 1]
                    regx_str = regex_for_range(int(rtlbl), int(next_rtlabel) - 1)
                else:
                    regx_str = regex_for_range(int(rtlbl), 999999)
                regex_dict[regx_str] = data_.get(rtlbl)
            
        elif no_of_rtlabels == 1:
            regx_str = ''
            key_list = list(data_.keys())
            rtlbl = key_list[0]
            regx_str = regex_for_range(int(rtlbl), 999999)
            regex_dict[regx_str] = data_.get(rtlbl)
        
        else:
            regx_str = ""

        for regxkey, val in regex_dict.items():
            if regxkey.endswith('|'):
                regxkey = regxkey[:-1]
            temp = '(' + regxkey + ')'
            temp = remove_unneeded_braces(temp)
            regxkey = '^' + temp + '-$conditionalEndPointTypes$'
            env_regx_map[regxkey] = val
    if default_value is not None or data == None:
        env_regx_map['^.*-$conditionalEndPointTypes$'] = default_value
        env_regx_map[''] = default_value
    return env_regx_map


def correction_in_proxy_config(parent_endpoint_extension):
    proxy_config_json_rearrange = {'apiTitle': parent_endpoint_extension['apiTitle'],
                                   'rest': parent_endpoint_extension['rest'],
                                   'proxyType': parent_endpoint_extension['proxyType'],
                                   'basePath': parent_endpoint_extension['basePath'],
                                   'manager': parent_endpoint_extension['manager'],
                                   'apicMigration': parent_endpoint_extension['apicMigration'],
                                   'policies': parent_endpoint_extension['policies']}

    proxy_config_json_endpoints = parent_endpoint_extension['x-EndpointExtension']
    endpoints_list_test = []
    endpoints_list_live = []

    for loop_data in proxy_config_json_endpoints:
        url = loop_data['Endpoint']['url']
        regex = loop_data['Endpoint']['rtlbl']['regx']
        if 'test.' in url and regex:
            if 'dr-' in url:
                existing_regex = loop_data['Endpoint']['rtlbl']['regx'].split("-")
                loop_data['Endpoint']['rtlbl']['regx'] = existing_regex[0] + '-dr' + existing_regex[1]
            if 'drn-' in url:
                existing_regex = loop_data['Endpoint']['rtlbl']['regx'].split("-")
                loop_data['Endpoint']['rtlbl']['regx'] = existing_regex[0] + '-drn' + existing_regex[1]
            endpoints_list_test.append(loop_data)
        elif 'live.' in url and 'dr-' not in url and 'drn-' not in url:
            endpoints_list_live.append(loop_data)

    proxy_config_json_rearrange['x-EndpointExtension'] = endpoints_list_test + endpoints_list_live

    return proxy_config_json_rearrange