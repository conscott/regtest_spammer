#!/usr/bin/env python3
import decimal
from multiprocessing.dummy import Pool as ThreadPool
import os
from rpc import NodeCLI, arg_to_cli
import time

# Round down to 8 places for satoshis calcs
decimal.getcontext().rounding = decimal.ROUND_DOWN

# 1 BTC = 10^8 statoshis
COIN = 10**8
# Dust limit
MIN_OUTPUT = 546 / COIN
# Max standard tx size is 100k
STD_TX_SIZE_LIMIT = 100000
# The mempool will allow a tx to have at most 25 ancestors before rejecting entry
STD_TX_ANCESTOR_LIMIT_MEMPOOL = 25
# Dirs for regtest data
DATA_DIR_SPAMMER = "./spamdir/"
DATA_DIR_MINER = "./minerdir/"


# Get tx size estimate for fees specifically between p2wpkh
def guess_sz(num_in, num_out):
    return num_in*68.5 + num_out*31 + 10.5


# want 1 sat/byte for a 1 input to 1 output tx
SIZE_OF_1_TO_1_P2PKWH = round(guess_sz(1, 1) / COIN, 8)
# Want to pay 1 sat/vbyte
DESIRED_FEE_PER_BYTE = 1
# STD FEE
DEFAULT_FEE = SIZE_OF_1_TO_1_P2PKWH * DESIRED_FEE_PER_BYTE
# Will be making chains of 25-txs spending each other
# and need to still be above dust limit at the end
TX_CHAIN_COST = round((DEFAULT_FEE * STD_TX_ANCESTOR_LIMIT_MEMPOOL) + MIN_OUTPUT, 8)

# The maximum std tx size is 100k.
# A one p2wpkh input tx has 79 vbytes and ~10 bytes for header
# data but inputs can be onther types so lets just reserve 220 bytes
MAX_OUTPUTS = int((STD_TX_SIZE_LIMIT - 220) / 32)

rpc = NodeCLI(os.getenv("BITCOINCLI", "bitcoin-cli"), datadir=DATA_DIR_SPAMMER)
miner = NodeCLI(os.getenv("BITCOINCLI", "bitcoin-cli"), datadir=DATA_DIR_MINER)


# Get satoshis from decimal btc amount
def sat(amt):
    return amt * COIN


# Wait until all our spent coins are confirmed
def wait_for_confirmation():
    while len(rpc.listunspent()) < 1:
        miner.generate(1)
        print("Waiting for confirmation...")
        time.sleep(1)


# Consolidate all balance into single utxo before start splitting
def consolidate():
    utxos = rpc.listunspent()[:2]
    balance = rpc.getbalance('*', 1)
    if len(utxos) > 1:
        father_of_spam = rpc.getnewaddress()

        print("Aggregating all coins to %s" % father_of_spam)
        # Subtract fee from entire amount with conf target of one week, which should
        # be close to 1 sat / byte
        rpc.sendtoaddress(father_of_spam, balance, "", "", True, False, 2)

        # Can only do on regtest
        wait_for_confirmation()
        print("Sent all %s coins to %s" % (balance, father_of_spam))
    else:
        print("Starting with 1 UTXO with balance %s" % balance)


# Make single transaction splitting entire wallet balance between many outputs
def create_many_utxos():
    confirmed_balance = rpc.getbalance('*', 1)
    amt_per_output = float(round(confirmed_balance / MAX_OUTPUTS, 8))
    num_outputs = MAX_OUTPUTS

    # Need each output to have at least enough btc to each make a chain
    # of 25 mempool transactions, each paying 1 sat/vbyte with
    # amounts above the dust limit
    if amt_per_output < TX_CHAIN_COST:
        num_outputs = int(confirmed_balance / TX_CHAIN_COST)
        amt_per_output = TX_CHAIN_COST

    print("Making transaction with %s btc in %s outputs" % (amt_per_output, MAX_OUTPUTS))
    print("This can take some time to generate...")
    addresses = [rpc.getnewaddress() for i in range(num_outputs)]
    outputs = {addr: amt_per_output for addr in addresses}

    # Have to use -stdin because the number of outputs and addresses may be too large
    # for bash default arg limit
    send_many_args = ('', outputs, 1, '', addresses, False, 2)
    formatted_input = '\n'.join(arg_to_cli(a) for a in send_many_args)
    txid = rpc('-datadir=%s' % DATA_DIR_SPAMMER, '-stdin', input=formatted_input).sendmany()
    # txid = rpc.sendmany("", outputs, 1, "making lots of outputs", addresses, False, 2)
    print("Txid is %s" % txid)
    wait_for_confirmation()
    print("Tx is confirmed")


# Make chain of mempool transactions spending the previous
def make_spending_chain(utxo):
    # Chain of 25 unspent outputs is the longest you can make
    for i in range(25):
        to_send = float(round(utxo['amount'] - DEFAULT_FEE, 8))
        if to_send < MIN_OUTPUT:
            break
        inputs = [{"txid": utxo["txid"], "vout": utxo["vout"]}]  # , "address": utxo["address"]}]
        to = rpc.getnewaddress()
        outputs = {to: to_send}
        # print("Spending %s and sending %s to %s" % (utxo['txid'], to_send, to))
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

# Get all coins in 1 UTXOs, don't actually need to this first
# consolidate()

# Split UTXO to many even amount UTXOs
create_many_utxos()

# See if it works
start_spamming()
