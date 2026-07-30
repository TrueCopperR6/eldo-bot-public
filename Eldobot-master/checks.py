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
        for d, v in default.items():
            if d in serversList[id]:
                continue
            else:
                serversList[id][d] = v
    else:
        serversList[id] = copy.deepcopy(default)
    serversList[id]['name'] = name
    return(serversList)
