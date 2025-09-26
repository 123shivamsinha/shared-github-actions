'''
Created on Nov 18, 2022

@author: y680550
'''
from common_config_utils import load_file


def get_swagger_tags(data):
    tags = data.get("tags")
    return tags


def get_swagger_tag_values(tags, tag_name):
    for tag in tags:
        if tag.get("name") == tag_name:
            value = tag.get("description")
            return value
