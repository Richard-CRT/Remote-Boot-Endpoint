import asyncio
import json
import sys
import websockets
import wakeonlan
from ping3 import ping

class Device():
    def __init__(self, name, mac, ip):
        self.Name = name;
        self.Mac = mac
        self.IP = ip
        self.PingDelay = None
    
    def boot(self):
        print(f"Sending magic packet to: {self.Mac}")
        wakeonlan.send_magic_packet(self.Mac)
    
    def ping(self):
        if self.IP is not None:
            self.PingDelay = ping(self.IP, timeout=0.5)

def get_config_dict():
    print("Loading config file...")
    filename = "endpoint_config.json"
    config_json = {"address": "", "targets": {}}

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
        print(f"Error decoding `{filename}` file - invalid JSON")
    except Exception as err:
        print(f"Error {type(err).__name__} while reading `{filename}` file")
        print(err)

    return config_json


def boot(device):
    print("-- Running boot procedure --")
    device.boot()

Devices = []
DeviceByMac = {}
DeviceByKey = {}
    
async def ping_loop():
    global Devices
    
    while True:
        for device in Devices:
            device.ping()
        await asyncio.sleep(10)

async def main():
    global DeviceByMac
    global DeviceByKey
    
    config_json = get_config_dict()
    uri = f"wss://{config_json['address']}:{config_json['port']}/?tgt=remote_boot"
    
    for target_key, target in config_json["targets"].items():
        if target["mac"] not in DeviceByMac:
            newDevice = Device(target["name"], target["mac"], target["ip"])
            Devices.append(newDevice)
            DeviceByMac[target["mac"]] = newDevice
        device = DeviceByMac[target["mac"]]
        DeviceByKey[target_key] = device
        
    asyncio.create_task(ping_loop())
    
    print(f"Connecting to {uri}...")
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
                                if key in DeviceByKey:
                                    print(f"Booting key {key}...")
                                    boot(DeviceByKey[key])
                        elif action == "request_ping":
                            if "key" in json_dict:
                                key = json_dict["key"]
                                if key in DeviceByKey:
                                    device = DeviceByKey[key]
                                    dict_message = {"client_type": "endpoint", "key": key, "ping": device.PingDelay}
                                    await websocket.send(json.dumps(dict_message))
        except websockets.ConnectionClosed:
            print(f"Connection closed, retrying...")
            continue
        except Exception as err:
            print(f"Error {type(err).__name__}")
            print(err)
            continue


if __name__ == "__main__":
    asyncio.run(main())
