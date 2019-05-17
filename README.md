## Description
Spam bitcoin (BTC, BCH, or BSV) for mempool experiments. Works for regtest, testnet, or mainnet.

By default the program will:

1. Consolidate the entire balance into one UTXO (consolidation). This step is skipped if the balance is already consolidated.
2. Split the entire balance into as many UTXOs as possible in a single transaction (split).
3. Take each UTXO and create chains of dependent txs submitted to the mempool in a loop until the program is terminated or the dust limit has been reached on all utxos (spam)

## Usage

Must have bitcoind install locally and python3

### Regtest Test Drive
```bash
# Start two regtest nodes. 1 miner and 1 spammer, and send 1 BTC to spammer
./start_regtest.sh
# Kick off the python spammer
./spam.py
```

You can call ther miner or spammer `bitcoin-cli` with
```
# Miner
bitcoin-cli -datadir=./minerdir <command>
# Spammer
bitcoin-cli -datadir=./spamdir <command>
```

### Command line options
```
spam.py -h

optional arguments:
  -h, --help          show this help message and exit
  --chain CHAIN       Choose fork: "BTC", "BCH", or "BSV" (default: "BTC")
  --feerate FEERATE   Chose fee-rate for spam in sat/byte (default: 1)
  --live              If supplied, will submit spam to local bitcoin node, rather than regtest nodes
  --only_consolidate  Only consolidate entire balance back into 1 UTXO. This can be called after spamming.
  --only_split        Only Split balance into many UTXOs.
  --only_spam         Start spamming on all existing UTXOs.
```
