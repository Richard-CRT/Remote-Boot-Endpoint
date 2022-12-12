import asyncio
import json
import sys
import websockets
import wakeonlan


def get_config_dict():
    print("Loading config file...")
    filename = "endpoint_config.json"
    config_json = {"targets": {}}

    try:
        with open(filename, 'r') as f:
            pass
    except FileNotFoundError:
        with open(filename, 'w') as f:
            json.dump(config_json, f)

    try:
        with open(filename, 'r') as f:
            config_json = json.load(f)
    except json.decoder.JSONDecodeError as e:
        print(f"Error decoding config.json file - invalid JSON")
    except Exception as err:
        print(f"Error {type(err).__name__} while reading config.json file")
        print(err)

    return config_json


def boot(key):
    print("-- Running boot procedure --")
    config_json = get_config_dict()
    if "targets" in config_json:
        if key in config_json["targets"]:
            for target_device in config_json["targets"][key]["devices"]:
                print(f"Sending magic packet to: {target_device['mac']}")
                wakeonlan.send_magic_packet(target_device['mac'])
    else:
        print("Didn't find required parameter 'targets' in config json")


async def main():
    config = get_config_dict()
    uri = f"wss://{config['address']}/?tgt=remote_boot"
    print(f"Connecting...")
    async for websocket in websockets.connect(uri):
        try:
            config_json = get_config_dict()
            dict_message = {"client_type": "endpoint", "keys": list(config_json["targets"].keys())}
            print(f"Sending: {dict_message}")
            await websocket.send(json.dumps(dict_message))
            async for message in websocket:
                try:
                    json_dict = json.loads(message)
                except json.decoder.JSONDecodeError as e:
                    pass
                else:
                    print(f"Received: {json_dict}")
                    if "action" in json_dict:
                        action = json_dict["action"]
                        if action == "boot":
                            if "key" in json_dict:
                                key = json_dict["key"]
                                print(f"Booting key {key}...")
                                boot(key)
        except websockets.ConnectionClosed:
            print(f"Connection closed, retrying...")
            continue
        except Exception as err:
            print(f"Error {type(err).__name__}")
            print(err)
            continue


if __name__ == "__main__":
    asyncio.run(main())
