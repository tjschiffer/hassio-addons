#!/bin/bash
set -e

CONFIG_PATH=/data/options.json

DD_API_KEY=$(jq --raw-output ".DD_API_KEY" $CONFIG_PATH)

sh -c "$(curl -L https://raw.githubusercontent.com/DataDog/dd-agent/master/packaging/datadog-agent/source/setup_agent.sh)"
