"""Stop ASGI body reads after an over-limit chunk, including middleware drains.

The bounded route reader returns HTTP 413. BaseHTTPMiddleware also listens for
client disconnects during the response; it must not keep consuming an attacker’s
remaining upload after that rejection. This wrapper retains no payload bytes.
"""
import anyio


class WebhookBodyBudgetMiddleware:
    def __init__(self, app, api_prefix='/api/v1', max_bytes=1_048_576):
        self.app = app
        self.api_prefix = api_prefix.rstrip('/')
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        path = scope.get('path', '')
        webhook = (
            path == self.api_prefix + '/billing/webhook'
            or path.startswith(self.api_prefix + '/shopify/webhooks/')
            or path.startswith('/webhook/delivery-failure/')
        )
        if scope['type'] != 'http' or not webhook:
            return await self.app(scope, receive, send)
        received = 0
        exceeded = False
        response_done = anyio.Event()

        async def bounded_receive():
            nonlocal received, exceeded
            if exceeded:
                # Wait for the 413 response to finish, not for more upload data.
                # Reporting disconnect too early would cancel the response body.
                await response_done.wait()
                return {'type': 'http.disconnect'}
            message = await receive()
            if message['type'] == 'http.request':
                received += len(message.get('body', b''))
                exceeded = received > self.max_bytes
            return message

        async def response_send(message):
            await send(message)
            if message['type'] == 'http.response.body' and not message.get('more_body', False):
                response_done.set()

        try:
            await self.app(scope, bounded_receive, response_send)
        finally:
            response_done.set()
