import asyncio
import json
import sys
import websockets
import wakeonlan
import ssl
import collections
import time
from ping3 import ping


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
            raw_val = ping(self.IP, timeout=0.5)
            if raw_val is None or raw_val == False:
                self.PingDelay = None
            else:
                self.PingDelay = raw_val * 1000

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


Devices = []
Device_by_MAC = {}
Device_by_UUID = {}

PriorityPingDevices = collections.deque()


async def ping_loop(websocket):
    global Devices

    lastGlobalPingTime = 0
    while True:
        if websocket is not None and websocket.open:
            while (len(PriorityPingDevices) > 0):
                priorityPingDevice = PriorityPingDevices.popleft()
                await priorityPingDevice.ping(websocket)

            currentTime = time.time()
            if currentTime - lastGlobalPingTime >= 10:
                for device in Devices:
                    await device.ping(websocket)
                lastGlobalPingTime = currentTime

            await asyncio.sleep(1)
        else:
            await asyncio.sleep(5)


async def main():
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

    ping_loop_task = None

    print(f"Connecting to {uri}...")
    try:
        # SSLContext(...) without protocol paramter is deprecated for 3.10 onwards
        async for websocket in websockets.connect(uri, ssl=ssl.SSLContext()):
            try:
                if ping_loop_task is not None:
                    ping_loop_task.cancel()
                    try:
                        await ping_loop_task
                    except asyncio.exceptions.CancelledError:
                        pass
                ping_loop_task = asyncio.create_task(ping_loop(websocket))

                config_json = get_config_dict()
                
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
                print(f"Connection closed, retrying...")
                continue
            except Exception as err:
                print(f"Error {type(err).__name__}")
                print(err)
                continue
    except Exception as err:
        print(f"Error {type(err).__name__}")
        print(err)


if __name__ == "__main__":
    asyncio.run(main())
