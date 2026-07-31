import json
import copy
import basics
import shared_info

serversList = shared_info.serversList

def server_check(id, name):
    default = serversList.get("default")

    if default is None:
        raise RuntimeError(
            "Default server configuration was not created."
        )
    id = str(id)
    if id in serversList:
       import copy

def merge_defaults(server, default):
    for k, v in default.items():
        if k not in server:
            server[k] = copy.deepcopy(v)
        elif isinstance(v, dict) and isinstance(server[k], dict):
            merge_defaults(server[k], v)
            if id in serversList:
                merge_defaults(serversList[id], default)
                    else:
                        serversList[id] = copy.deepcopy(default)
                    else:
                        serversList[id] = copy.deepcopy(default)
    serversList[id]['name'] = name
    return(serversList)
