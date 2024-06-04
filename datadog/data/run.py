#!/usr/bin/env python3

import json
import os
import asyncio
import websockets
import requests
import datetime
import logging
from datadog_api_client import ApiClient, Configuration
from datadog_api_client.v2.api.metrics_api import MetricsApi
from datadog_api_client.v2.model.metric_content_encoding import MetricContentEncoding
from datadog_api_client.v2.model.metric_intake_type import MetricIntakeType
from datadog_api_client.v2.model.metric_payload import MetricPayload
from datadog_api_client.v2.model.metric_point import MetricPoint
from datadog_api_client.v2.model.metric_series import MetricSeries

from datadog_api_client import ApiClient, Configuration
from datadog_api_client.v1.api.events_api import EventsApi
from datadog_api_client.v1.model.event_create_request import EventCreateRequest

logging.basicConfig(format="%(asctime)s:" + logging.BASIC_FORMAT)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# TODO: Make prefix an Option like the integration does
prefix = "hass"
SUPERVISOR_TOKEN = os.getenv("SUPERVISOR_TOKEN")

# Copied from homeassistant/helpers/state.py
# https://github.com/home-assistant/core/blob/dev/homeassistant/helpers/state.py#L75
def stateAsNumber(state: str) -> float:
    """Try to coerce our state to a number.

    Raises ValueError if this is not possible.
    """
    if state in (
        "on",  # STATE_ON
        "locked",  # STATE_LOCKED,
        "above_horizon",  # STATE_ABOVE_HORIZON,
        "open",  # STATE_OPEN,
        "home",  # STATE_HOME,
    ):
        return 1
    if state in (
        "off",  # STATE_OFF
        "unlocked",  # STATE_UNLOCKED,
        "unknown",  # STATE_UNKNOWN,
        "below_horizon",  # STATE_BELOW_HORIZON,
        "closed",  # STATE_CLOSED
        "not_home",  # STATE_NOT_HOME,
    ):
        return 0

    value = None
    try:
        value = float(state)
    except:
        pass
    return value


async def sendMetricToDatadog(
    metric_name: str,
    timestamp: datetime,
    value: float,
    tags: list[str],
    unit: str = None,
):
    body = MetricPayload(
        series=[
            MetricSeries(
                metric=metric_name,
                type=MetricIntakeType.GAUGE,
                points=[
                    MetricPoint(
                        timestamp=int(timestamp.timestamp()),
                        value=value,
                    ),
                ],
                tags=tags,
                unit=unit,
            ),
        ],
    )

    configuration = Configuration()
    with ApiClient(configuration) as api_client:
        api_instance = MetricsApi(api_client)
        response = api_instance.submit_metrics(
            content_encoding=MetricContentEncoding.ZSTD1, body=body
        )

        if len(response['errors']) > 0:
            logger.error('Error sending metric to Datadog')
            for error in response['errors']:
                logger.error(error)


async def forwardStatesToMetrics():
    async for websocket in websockets.connect("ws://supervisor/core/websocket"):
        await websocket.send(
            json.dumps(
                {
                    "type": "auth",
                    "access_token": SUPERVISOR_TOKEN,
                }
            )
        )
        await websocket.send(json.dumps({'id': 1, 'type': 'subscribe_events', 'event_type': 'state_changed'}))

        while True:
            try:
                message = await websocket.recv()
            except websockets.ConnectionClosed:
                break
            try:
                data = json.loads(message)
                if (
                    data["type"] != "event"
                    or data["event"]["event_type"] != "state_changed"
                ):
                    continue

                new_state = data["event"]["data"]["new_state"]
                domain = new_state['device_class'] if 'device_class' in new_state else new_state["entity_id"].split(".")[0]
                metric_name = f"{prefix}.{domain}".replace(" ", "_")
                state = new_state["state"]
                value = (
                    state
                    if isinstance(state, (float, int))
                    else stateAsNumber(state)
                )
                tags = [f"entity:{new_state['entity_id']}"]
                if "friendly_name" in new_state["attributes"]:
                    tags.append(f"friendly_name:{new_state['attributes']['friendly_name']}")
                unit = (
                    new_state["attributes"]["unit_of_measurement"]
                    if "unit_of_measurement" in new_state["attributes"]
                    else None
                )

                timestamp = datetime.datetime.fromisoformat(new_state["last_changed"])

                if value is not None:
                    # Do not wait for this task to be completed, just loop and wait for next message
                    asyncio.create_task(
                        sendMetricToDatadog(
                            metric_name=metric_name,
                            timestamp=timestamp,
                            value=value,
                            tags=tags,
                            unit=unit,
                        )
                    )
                else:
                    pass
                    # Ignore event if state is not number and cannot be converted to a number

            except Exception as e:
                logger.error(e)

TIME_ZONE = datetime.datetime.now().astimezone().tzinfo
def generateMessage(name: str, state: str) -> str:
    if name == "Sun":
        adjective = "rose" if state == "above_horizon" else "set"
        return f"Sun {adjective}"

    adjective = "changed to"
    if state in ["on", "off"]:
        adjective = "turned"
    if state in ["unlocked", "locked", "open", "closed", "connected", "disconnected"]:
        adjective = "was"
    if state in ["available", "unavailable"]:
        adjective = "became"

    updatedState = state
    try:
        timestamp = datetime.datetime.fromisoformat(state)
        updatedState = timestamp.astimezone(TIME_ZONE).strftime("%B %e, %Y at %-I:%M %p")
    except Exception:
        pass

    return f"{name} {adjective} {updatedState}"

async def sendEventToDatadog(timestamp: datetime, title: str, text: str, tags: list[str]):
    body = EventCreateRequest(
        date_happened=int(timestamp.timestamp()),
        title=title,
        text=text,
        tags=tags,
    )


    configuration = Configuration()
    with ApiClient(configuration) as api_client:
        api_instance = EventsApi(api_client)
        response = api_instance.create_event(body=body)

        if response.status != 'ok':
            logger.error(f'Failed to send event to Datadog: {text}')
        


async def forwardLogbookToEvents():
    headers =  {
        "Authorization": f"Bearer {SUPERVISOR_TOKEN}",
    }
    # intialize timestamp to 10 seconds ago
    timestamp = (datetime.datetime.now() - datetime.timedelta(seconds=10)).isoformat()
    while True:
        try:
            api_url = f"http://supervisor/core/api/logbook/{timestamp}"
            response = requests.get(api_url, headers=headers)
            events = response.json()
            for event in events:
                timestamp = datetime.datetime.fromisoformat(event["when"])
                name = event["name"]
                if "message" in event:
                    message = f"{name} {event['message']}"
                else:
                    message = generateMessage(event["name"], event["state"])
                tags = [f"entity:{event['entity_id']}"]
                if ('domain' in event):
                    tags.append(f"domain:{event['domain']}")
                # Do not wait for this task to be completed, just loop and send the next event
                asyncio.create_task(
                    sendEventToDatadog(
                        timestamp=timestamp,
                        title=message,
                        text=json.dumps(event),
                        tags=tags
                    )
                )
            if (len(events) > 0):
                timestamp = events[-1]["when"]
        except Exception as e:
            logger.error(e)
        await asyncio.sleep(10)
        

async def main():
    logger.info('Starting data collection')
    await asyncio.gather(forwardStatesToMetrics(), forwardLogbookToEvents())

if __name__ == "__main__":
    asyncio.run(main())