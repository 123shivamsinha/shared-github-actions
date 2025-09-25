# @PydevCodeAnalysisIgnore
import json
import os
from common_config_utils import load_file
from common_config_utils import replace_placeholder
from common_config_utils import convert_rtlbl_in_regx
from common_config_utils import correction_in_proxy_config
from common_config_utils import value_from_json_path
from common_config_utils import value_from_json_field
from swagger_utils import get_swagger_tags
from swagger_utils import get_swagger_tag_values


def create_proxy_config_files(proxy_config_template_file_path, source_mapping_agent_file_path, file_gen_path, swagger_file_path, env_stack_file_path, routlbl_file_path, endpoint_type_file_path):
    
    def get_file_path_by_name(current_file_name):
        if current_file_name == 'swagger':
            return swagger_file_path
        if current_file_name == 'env-stack':
            return env_stack_file_path
        if current_file_name == 'routlabels':
            return routlbl_file_path
        if current_file_name == 'endpointTypes':
            return endpoint_type_file_path
        return '' 
    
    access_type = get_swagger_tag_values(get_swagger_tags(load_file(swagger_file_path)), 'x-accessType')
    if access_type == None:
        access_type = 'internal'
    
    proxy_config = load_file(proxy_config_template_file_path)
    source_mapping = load_file(source_mapping_agent_file_path)
    endpoint_extension_array_internal = []
    endpoint_extension_array_external = []
    endpoint_extension_array_internal_ext = []
    endpoint_extension_array_external_ext = []
    proxy_config_parent = {}
    service_default_version = ''
    for key, value in source_mapping.items():
        data = load_file(get_file_path_by_name(key))
        if key == 'env-stack':
            x_team_org = get_swagger_tag_values(get_swagger_tags(load_file(swagger_file_path)), 'x-team-org')
            data = data.get(x_team_org)
        for source in value:
            tag_name = source.get("source")
            source_type = source.get("sourceType")
            destination = source.get("destination")
            if source_type == 'tag':
                source_value = get_swagger_tag_values(get_swagger_tags(data), tag_name)
                if tag_name == 'x-default-version':
                    service_default_version = source_value
                proxy_config = replace_placeholder(proxy_config, destination, source_value)
            elif source_type == 'direct':
                source_value = value_from_json_field(data, tag_name)
                proxy_config = replace_placeholder(proxy_config, destination, source_value)
            elif source_type.startswith('loop'):
                loop_internal_parent_elements = source.get('loopInternalParentElements')
                loop_external_parent_elements = source.get('loopExternalParentElements')
                loop_main_elements = source.get('loopMainElements')
                parent_internal_endpoint_extension = value_from_json_path(proxy_config, loop_internal_parent_elements)
                parent_external_endpoint_extension = value_from_json_path(proxy_config, loop_external_parent_elements)
                internal_ = value_from_json_path(proxy_config, loop_internal_parent_elements + '.' + loop_main_elements)
                external_ = value_from_json_path(proxy_config, loop_external_parent_elements + '.' + loop_main_elements)
                internal_copy_ = internal_
                external_copy_ = external_
                mappings = source.get('mappings')
                inner_loop_files = source.get('inner-loop-files')
                for env in data:
                    if inner_loop_files is not None: 
                        for inner_data in inner_loop_files:
                                inner_file = load_file(get_file_path_by_name(inner_data.get('fileName')))
                                inner_mappings = inner_data.get('mappings')
                                for inner_mapping in inner_mappings:
                                    inner_destination_ = inner_mapping.get('destination')
                                    # target_version = inner_file.get('default')
                                    env_regx_map = convert_rtlbl_in_regx(inner_file, env.get('name'), service_default_version)
                                    for key, value in env_regx_map.items():
                                        internal_copy_ = replace_placeholder(internal_copy_, inner_destination_, value)
                                        external_copy_ = replace_placeholder(external_copy_, inner_destination_, value)
                                        internal_copy_ = replace_placeholder(internal_copy_, "$rtlbl", key)
                                        external_copy_ = replace_placeholder(external_copy_, "$rtlbl", key)
                                        for mapping in mappings:
                                            source_ = mapping.get('source')
                                            destination_ = mapping.get('destination')
                                            internal_copy_ = replace_placeholder(internal_copy_, destination_, env.get(source_))
                                            external_copy_ = replace_placeholder(external_copy_, destination_, env.get(source_))
                                        endpoint_extension_array_internal_ext = endpoint_extension_array_internal_ext + internal_copy_
                                        endpoint_extension_array_external_ext = endpoint_extension_array_external_ext + external_copy_
                                        internal_copy_ = internal_
                                        external_copy_ = external_
                    else:
                        for mapping in mappings:
                            source_ = mapping.get('source')
                            destination_ = mapping.get('destination')
                            if env.get(source_) is not None and env.get(source_) == 'live':
                                internal_copy_ = replace_placeholder(endpoint_extension_array_internal_ext, destination_, env.get(source_))
                                external_copy_ = replace_placeholder(endpoint_extension_array_external_ext, destination_, env.get(source_))
                                internal_copy_ = replace_placeholder(internal_copy_, '-$conditionalEndPointTypes', '')
                                external_copy_ = replace_placeholder(external_copy_, '-$conditionalEndPointTypes', '')
                            else:
                                internal_copy_ = replace_placeholder(endpoint_extension_array_internal_ext, destination_, env.get(source_))
                                external_copy_ = replace_placeholder(endpoint_extension_array_external_ext, destination_, env.get(source_)) 
                                internal_copy_ = replace_placeholder(internal_copy_, '$conditionalEndPointTypes', env.get(source_))
                                external_copy_ = replace_placeholder(external_copy_, '$conditionalEndPointTypes', env.get(source_))
                                   
                            endpoint_extension_array_internal = endpoint_extension_array_internal + internal_copy_
                            endpoint_extension_array_external = endpoint_extension_array_external + external_copy_
    parent_internal_endpoint_extension[loop_main_elements] = endpoint_extension_array_internal
    parent_external_endpoint_extension[loop_main_elements] = endpoint_extension_array_external
    
    parent_internal_endpoint_extension = correction_in_proxy_config(parent_internal_endpoint_extension)
    parent_external_endpoint_extension = correction_in_proxy_config(parent_external_endpoint_extension)
   
    proxy_list = []
    if access_type == 'internal' or access_type == 'both':
        proxy_config_parent['proxyConfig'] = parent_internal_endpoint_extension
        proxy_config_parent['proxyConfig']['proxyType'] = 'internal'
        proxy_list.append('internal')
         # Below line to create the defination folder if doesn't exist
        os.makedirs(file_gen_path, exist_ok=True)
        internal = open(file_gen_path + "/proxyConfig-internal.json", "w")
        internal.write(json.dumps(proxy_config_parent, indent=3))
        internal.close()
    
    if access_type == 'external' or access_type == 'both':
        proxy_config_parent['proxyConfig'] = parent_external_endpoint_extension
        proxy_config_parent['proxyConfig']['proxyType']='external'
        proxy_list.append('external')
        # Below line to create the defination folder if doesn't exist
        os.makedirs(file_gen_path, exist_ok=True)
        external = open(file_gen_path + "/proxyConfig-external.json", "w")
        external.write(json.dumps(proxy_config_parent, indent=3))
        external.close()
    
    return proxy_list