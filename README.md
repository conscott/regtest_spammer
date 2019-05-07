## Description
Spam bitcoin regtest for mempool experiments 

## Usage

Must have bitcoind install locally and python3

```bash
# Start two regtest nodes. 1 miner and 1 spammer, and send 1 BTC to spammer
./start_regtest.sh
# Kick off the python spammer
./spam.py
```

You can call ther miner or spammer bitcoin-cli with
```
# Miner
bitcoin-cli -datadir=./minerdir <command>
# Spammer
bitcoin-cli -datadir=./spamdir <command>
```
