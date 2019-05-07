#!/usr/bin/env python3
import decimal
from multiprocessing.dummy import Pool as ThreadPool
import os
from rpc import NodeCLI
import time

# Round down to 8 places
decimal.getcontext().rounding = decimal.ROUND_DOWN

COIN = 10**8
MIN_OUTPUT = 546 / COIN
STD_LIMIT = 100000

# Maximum number of outputs in standard p2sh transaction
#MAX_OUTPUTS = 2935
MAX_OUTPUTS = 5

DATA_DIR_SPAMMER = "./spamdir/"
DATA_DIR_MINER = "./minerdir/"
rpc = NodeCLI(os.getenv("BITCOINCLI", "bitcoin-cli"), datadir=DATA_DIR_SPAMMER)
miner = NodeCLI(os.getenv("BITCOINCLI", "bitcoin-cli"), datadir=DATA_DIR_MINER)


# Get tx size estimate for fees
def guess_sz(num_in, num_out):
    return num_in*149 + num_out*32 + 10


# want one sat / byte for a 1 to 1 tx
STD_FEE = round(guess_sz(1, 1) / COIN, 8)


def sat(amt):
    return amt * COIN


def wait_for_confirmation():
    while len(rpc.listunspent()) < 1:
        miner.generate(1)
        print("Waiting for confirmation...")
        time.sleep(1)


# Consolidate all balance into single utxo before start splitting
def consolidate():
    utxos = rpc.listunspent()[:2]
    if len(utxos) > 1:
        father_of_spam = rpc.getnewaddress()
        balance = rpc.getbalance('*', 1)

        print("Aggregating all coins to %s" % father_of_spam)
        # Subtract fee from entire amount with conf target of one week, which should
        # be close to 1 sat / byte
        rpc.sendtoaddress(father_of_spam, rpc.getbalance('*', 1), "", "", True, False, 2)

        # Can only do on regtest
        wait_for_confirmation()
        print("Sent all %s coins to %s" % (balance, father_of_spam))
    else:
        print("Starting with 1 UTXO with balance %s" % rpc.getbalance('*', 1))


# Make single transaction splitting entire wallet balance between many outputs
def create_many_utxos():
    # Tx to make a ton of UTXOs
    amt_per_output = round(float(rpc.getbalance('*', 1)) / MAX_OUTPUTS, 8)
    print("Sending %s to %s outputs" % (amt_per_output, MAX_OUTPUTS))
    addresses = [rpc.getnewaddress() for i in range(MAX_OUTPUTS)]
    outputs = {addr: amt_per_output for addr in addresses}
    txid = rpc.sendmany("", outputs, 1, "making lots of outputs", addresses, False, 2)
    print("Txid is %s" % txid)

    wait_for_confirmation()
    print("Tx is confirmed")


# Make chain of mempool transactions spending the previous
def make_spending_chain(utxo):
    # Chain of 25 unspent outputs is the longest you can make
    for i in range(25):
        to_send = round(float(utxo['amount']) - STD_FEE, 8)
        if to_send < MIN_OUTPUT:
            break
        inputs = [{"txid": utxo["txid"], "vout": utxo["vout"]}]  # , "address": utxo["address"]}]
        to = rpc.getnewaddress()
        outputs = {to: to_send}
        #print("Spending %s and sending %s to %s" % (utxo['txid'], to_send, to))
        rawtx = rpc.createrawtransaction(inputs, outputs)
        signresult = rpc.signrawtransactionwithwallet(rawtx)
        txid = rpc.sendrawtransaction(signresult["hex"], False)

        # Set the next uxto to spend to be this transaction
        utxo = {'txid': txid, 'vout': 0, 'amount': to_send}


# function to be mapped over
def spam_parallel(utxos, threads=4):
    pool = ThreadPool(threads)
    pool.map(make_spending_chain, utxos)
    pool.close()
    pool.join()


def start_spamming():
    utxos = rpc.listunspent()
    print("Creating 25 tx chains for %s utxos, this may take some time...." % len(utxos))
    spam_parallel(utxos)
    mempool = rpc.getmempoolinfo()
    print("Have mempool of %s transactions and %s MB" % (mempool['size'], round(mempool['bytes'] / 1048576.0, 3)))


balance = rpc.getbalance('*', 1)
assert balance > 0.01

# Get all coins in 1 UTXOs
consolidate()

# Split UTXO to many even amount UTXOs
create_many_utxos()

# See if it works
start_spamming()
