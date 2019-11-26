#!/bin/bash

echo "Killing all bitcoind"
killall bitcoind

sleep 2

echo "Starting new daemons"

rm -rf ./minerdir/*
rm -rf ./spamdir/*

cp miner.conf minerdir/bitcoin.conf
cp spammer.conf spamdir/bitcoin.conf

BITCOIN_VERSION=$(bitcoind --version | grep 'version v' | tr ' ' '\n' | tail -n 1)
BITCOIN_MAJOR=$(echo "$BITCOIN_VERSION" | tr '.' '\n' | head -n 2 | tail -n 1)

echo "Using Bitcoin Major Version $BITCOIN_MAJOR"

# Start mining node
bitcoind -datadir=./minerdir -fallbackfee='0.00000001' -daemon

# Start spamming node
bitcoind -datadir=./spamdir -fallbackfee='0.00000001' -daemon

echo "Connecting nodes..."
sleep 5

# Have mining node add spamming node connect
bitcoin-cli -datadir=./spamdir/ addnode 127.0.0.1:18444 add
sleep 1

echo "Mining blocks to send to spammer"
if [[ $BITCOIN_MAJOR -gt 18 ]]; then
    ADDRESS_MINER=$(bitcoin-cli -datadir=./minerdir/ getnewaddress)
    ADDRESS_SPAMMER=$(bitcoin-cli -datadir=./spamdir/ getnewaddress)
    bitcoin-cli -datadir=./minerdir/ generatetoaddress 101 "$ADDRESS_MINER"
    bitcoin-cli -datadir=./minerdir/ sendtoaddress "$ADDRESS_SPAMMER" '0.05'
    sleep 1
    bitcoin-cli -datadir=./minerdir/ generatetoaddress 1 "$ADDRESS_MINER"
    sleep 1
else
    ADDRESS_SPAMMER=$(bitcoin-cli -datadir=./spamdir/ getnewaddress)
    bitcoin-cli -datadir=./minerdir/ generate 101
    bitcoin-cli -datadir=./minerdir/ sendtoaddress "$ADDRESS_SPAMMER" '0.05'
    sleep 1
    bitcoin-cli -datadir=./minerdir/ generate 1
    sleep 1
fi

BALANCE=$(bitcoin-cli -datadir=./spamdir/ getbalance)
echo "Spammer has $BALANCE btc"

echo "Done."
