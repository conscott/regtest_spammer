#!/bin/bash

echo "Killing all bitcoind"
killall bitcoind

sleep 2

echo "Starting new daemons"

rm -rf ./minerdir/*
rm -rf ./spamdir/*

cp miner.conf minerdir/bitcoin.conf
cp spammer.conf spamdir/bitcoin.conf

# Start mining node
bitcoind -datadir=./minerdir -daemon

# Start spamming node
bitcoind -datadir=./spamdir -daemon 

echo "Connecting nodes..."
sleep 5

# Have mining node add spamming node connect
bitcoin-cli -datadir=./spamdir/ addnode 127.0.0.1:18444 add
sleep 1

echo "Mining blocks to send to spammer"
bitcoin-cli -datadir=./minerdir/ generate 101
bitcoin-cli -datadir=./minerdir/ sendtoaddress `bitcoin-cli -datadir=./spamdir/ getnewaddress` '0.5'
sleep 1
bitcoin-cli -datadir=./minerdir/ generate 1
sleep 1

BALANCE=$(bitcoin-cli -datadir=./spamdir/ getbalance)
echo "Spammer has $BALANCE btc"

echo "Done."
