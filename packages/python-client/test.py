import asyncio
import engineio
import os
import aiohttp
import rpc_reader
import plugin_remote
from plugin_remote import SystemManager, MediaManager
from scrypted_python.scrypted_sdk import ScryptedStatic

class EioRpcTransport(rpc_reader.RpcTransport):
    message_queue = asyncio.Queue()

    def __init__(self, loop: asyncio.AbstractEventLoop):
        super().__init__()
        self.eio = engineio.AsyncClient(ssl_verify=False)
        self.loop = loop

        @self.eio.on("message")
        def on_message(data):
            self.message_queue.put_nowait(data)

    async def read(self):
        return await self.message_queue.get()

    def writeBuffer(self, buffer, reject):
        self.writeBuffer(buffer, reject)

    def writeJSON(self, json, reject):
        async def send():
            try:
                await self.eio.send(json)
            except Exception as e:
                reject(e)
        asyncio.run_coroutine_threadsafe(send(), self.loop)


async def connect_scrypted_client(
    base_url: str, username: str, password: str, plugin_id: str = "@scrypted/core"
):
    login_url = f"{base_url}/login"
    login_body = {
        "username": username,
        "password": password,
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            login_url, verify_ssl=False, json=login_body
        ) as response:
            login_response = await response.json()

            headers = {"Authorization": login_response["authorization"]}

            loop = asyncio.get_event_loop()
            transport = EioRpcTransport(loop)

            await transport.eio.connect(
                base_url,
                headers=headers,
                engineio_path=f"/endpoint/{plugin_id}/engine.io/api/",
            )
            
            ret = asyncio.Future[ScryptedStatic](loop=loop)
            peer, peerReadLoop = await rpc_reader.prepare_peer_readloop(loop, transport)
            peer.params['print'] = print
            def callback(api, pluginId, hostInfo):
                remote = plugin_remote.PluginRemote(peer, api, pluginId, hostInfo, loop)
                wrapped = remote.setSystemState
                async def remoteSetSystemState(systemState):
                    await wrapped(systemState)
                    async def resolve():
                        sdk = ScryptedStatic()
                        sdk.api = api
                        sdk.remote = remote
                        sdk.systemManager = SystemManager(api, remote.systemState)
                        sdk.mediaManager = MediaManager(await api.getMediaManager())
                        ret.set_result(sdk)
                    asyncio.run_coroutine_threadsafe(resolve(), loop)
                remote.setSystemState = remoteSetSystemState
                return remote
            peer.params['getRemote'] = callback
            asyncio.run_coroutine_threadsafe(peerReadLoop(), loop)

            sdk = await ret
            return sdk

async def main():
    sdk = await connect_scrypted_client(
        "https://localhost:10443",
        os.environ["SCRYPTED_USERNAME"],
        os.environ["SCRYPTED_PASSWORD"],
    )

    for id in sdk.systemManager.getSystemState():
        device = sdk.systemManager.getDeviceById(id)
        print(device.name)
    os._exit(0)

loop = asyncio.new_event_loop()
asyncio.run_coroutine_threadsafe(main(), loop)
loop.run_forever()
