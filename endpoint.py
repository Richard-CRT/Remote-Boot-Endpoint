import asyncio
import json
import sys
from websockets.asyncio.client import connect
import websockets
import websockets.protocol
import wakeonlan
import ssl
import collections
import time
import ping3
ping3.EXCEPTIONS = True

class Device():
    def __init__(self, uuid, name, mac, ip):
        self.UUID = uuid
        self.Name = name
        self.Mac = mac
        self.IP = ip
        self.PingDelay = None

    def boot(self):
        print(f"Sending magic packet to: {self.Mac}")
        wakeonlan.send_magic_packet(self.Mac)

    async def ping(self, websocket):
        if self.IP is not None:
            try:
                self.PingDelay = ping3.ping(self.IP, timeout=0.5) * 1000
            except ping3.errors.PingError:
                self.PingDelay = None

            json_string = json.dumps({"action": "ping", "uuid": self.UUID, "ping_ms": self.PingDelay})
            print(f"Sending: {json_string}")
            await websocket.send(json_string)


def get_config_dict():
    print("Loading config file...")
    filename = "endpoint_config.json"
    config_json = {"address": "hostname.com", "port": "1234", "targets": {}}

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


Websocket = None
Devices = []
Device_by_MAC = {}
Device_by_UUID = {}

PriorityPingDevices = collections.deque()


async def ping_loop():
    global Websocket
    global Devices

    lastGlobalPingTime = 0
    while True:
        if Websocket is not None and Websocket.state == websockets.protocol.State.OPEN:
            while len(PriorityPingDevices) > 0:
                priorityPingDevice = PriorityPingDevices.popleft()
                await priorityPingDevice.ping(Websocket)

            currentTime = time.time()
            if currentTime - lastGlobalPingTime >= 10:
                for device in Devices:
                    await device.ping(Websocket)
                lastGlobalPingTime = currentTime

            await asyncio.sleep(1)
        else:
            await asyncio.sleep(5)


async def main():
    global Websocket
    global Device_by_MAC
    global Device_by_UUID
    global PriorityPingDevices

    config_json = get_config_dict()
    uri = f"wss://{config_json['address']}:{config_json['port']}/?tgt=remote_boot&client_type=endpoint"

    for target_uuid, target in config_json["targets"].items():
        if target["mac"] not in Device_by_MAC:
            newDevice = Device(target_uuid, target["name"], target["mac"], target["ip"])
            Devices.append(newDevice)
            Device_by_MAC[target["mac"]] = newDevice
        device = Device_by_MAC[target["mac"]]
        Device_by_UUID[target_uuid] = device

    ping_loop_task = asyncio.create_task(ping_loop())

    print(f"Connecting to {uri}...")
    try:
        # SSLContext(...) without protocol paramter is deprecated for 3.10 onwards
        async for websocket in connect(uri, ssl=True):
            Websocket = websocket
            try:
                json_string = json.dumps({"action": "register", "uuids": list(config_json["targets"].keys())})
                print(f"Sending: {json_string}")
                await websocket.send(json_string)
                
                async for message in websocket:
                    try:
                        json_dict = json.loads(message)
                    except json.decoder.JSONDecodeError as e:
                        pass
                    else:
                        print(f"Received: {json_dict}")
                        if "action" in json_dict:
                            action = json_dict["action"]
                            if action == "request_boot":
                                if "uuid" in json_dict:
                                    uuid = json_dict["uuid"]
                                    if uuid in Device_by_UUID:
                                        print(f"Booting UUID {uuid}...")
                                        boot(Device_by_UUID[uuid])
                            elif action == "request_ping":
                                if "uuid" in json_dict:
                                    uuid = json_dict["uuid"]
                                    if uuid in Device_by_UUID:
                                        device = Device_by_UUID[uuid]
                                        if device not in PriorityPingDevices:
                                            PriorityPingDevices.append(device)
            except websockets.ConnectionClosed:
                print(f"Connection closed")
            except Exception as err:
                print(f"Error {type(err).__name__}")
                print(err)
            
            print(f"Waiting slow-down period...")
            await asyncio.sleep(5)
            print(f"Retrying connection...")
    except Exception as err:
        print(f"Error {type(err).__name__}")
        print(err)


if __name__ == "__main__":
    asyncio.run(main())
