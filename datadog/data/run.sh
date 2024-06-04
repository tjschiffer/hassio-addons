#!/usr/bin/with-contenv bashio

DD_SITE=$(bashio::config 'DD_SITE') DD_API_KEY=$(bashio::config 'DD_API_KEY') python ./run.py