#!/usr/bin/env python3
import decimal
from decimal import Decimal
from multiprocessing.dummy import Pool as ThreadPool
import os
from rpc import NodeCLI, arg_to_cli
import time

# Round down to 8 places for satoshis calcs
decimal.getcontext().rounding = decimal.ROUND_DOWN

# 1 BTC = 10^8 statoshis
COIN = 10**8
# Dust limit for p2pkh
MIN_OUTPUT = 546 / COIN
# Max standard tx size is 100k bytes
STD_TX_SIZE_LIMIT = 100000
# The mempool will allow a tx to have at most 25 ancestors before rejecting entry
DEFAULT_ANCESTOR_LIMIT = 25
# Dirs for regtest data
DATA_DIR_SPAMMER = "./spamdir/"
DATA_DIR_MINER = "./minerdir/"

# If using segwit native addr (bech32), calculate vbytes, otherwise assuming using
# standard p2pkh transactions
SEGWIT = False

# Get tx size estimate
if SEGWIT:
    # Segwit get dat discount
    def guess_sz(num_in, num_out):
        return num_in*68.5 + num_out*31 + 10.5
else:
    # P2PKH still got dat lame bytes
    def guess_sz(num_in, num_out):
        return num_in*148 + num_out*34 + 10

# Could try this on other chains as well
BTC = True
BCH = False
BSV = False
if BTC:
    # MAX blocksize for BTC in vbytes
    MAX_BLOCK = 1000000
elif BCH:
    # MAX blocksize for BCH in bytes
    MAX_BLOCK = 32000000
elif BSV:
    # MAX blocksize for BSV in bytes
    MAX_BLOCK = 128000000


# want 1 sat/byte for a 1 input to 1 output tx
SIZE_OF_1_TO_1_TX = guess_sz(1, 1)
# Want to pay 1 sat/vbyte
DESIRED_FEE_PER_BYTE = 1
# STD FEE
DEFAULT_FEE = round(SIZE_OF_1_TO_1_TX * DESIRED_FEE_PER_BYTE / COIN, 8)
# Will be making chains of 25-txs spending each other
# and need to still be above dust limit at the end
TX_CHAIN_COST = round((DEFAULT_FEE * DEFAULT_ANCESTOR_LIMIT) + MIN_OUTPUT, 8)

# The maximum std tx size is 100k.
# A one p2wpkh input tx has 79 vbytes and ~10 bytes for header
# data but inputs can be onther types so lets just reserve extra bytes
if SEGWIT:
    MAX_OUTPUTS = int((STD_TX_SIZE_LIMIT - 220) / 32)
else:
    MAX_OUTPUTS = int((STD_TX_SIZE_LIMIT - 400) / 34)


# Going to make txs with max number of outputs that can all be independently chained in mempool
# If the entire set is less than a block you can can make multiple MAX_OUTPUT txs
SPAM_SIZE_PER_OUTPUT_SET = (DEFAULT_ANCESTOR_LIMIT * MAX_OUTPUTS * SIZE_OF_1_TO_1_TX)

REGTEST = True

# Finally setup the RPC objects
if REGTEST:
    rpc = NodeCLI(os.getenv("BITCOINCLI", "bitcoin-cli"), datadir=DATA_DIR_SPAMMER)
    miner = NodeCLI(os.getenv("BITCOINCLI", "bitcoin-cli"), datadir=DATA_DIR_MINER)
else:
    rpc = NodeCLI(os.getenv("BITCOINCLI", "bitcoin-cli"))


def print_debug_info():
    print("Using segwit is %s" % SEGWIT)
    print("A one input -> one output tx is %s bytes" % SIZE_OF_1_TO_1_TX)
    print("Max number of outputs per tx is %s" % MAX_OUTPUTS)
    print("The cost to make a chain of 25 mempool txs is %s sat" % (TX_CHAIN_COST * COIN))
    print("A chain of 25 txs for %s outputs is %s MB" % (MAX_OUTPUTS, SPAM_SIZE_PER_OUTPUT_SET / 1000000))


# Get satoshis from decimal btc amount
def sat(amt):
    return amt * COIN


# Wait until all our spent coins are confirmed
def wait_for_confirmation(txs_to_confirm=1):
    while len(rpc.listunspent()) < txs_to_confirm:
        if REGTEST:
            miner.generate(1)
            time.sleep(1)
        else:
            time.sleep(60)
        print("Waiting for confirmation of %s tx" % txs_to_confirm)


# Consolidate all balance into single utxo before start splitting
def consolidate():
    utxos = rpc.listunspent()[:2]
    balance = rpc.getbalance('*', 1)
    if len(utxos) > 1:
        father_of_spam = rpc.getnewaddress()

        print("Aggregating all coins to %s" % father_of_spam)
        # Subtract fee from entire amount with conf target of one week, which should
        # be close to 1 sat / byte
        rpc.sendtoaddress(father_of_spam, balance, "", "", True, False, 1008)
        wait_for_confirmation()
        print("Sent all %s coins to %s" % (balance, father_of_spam))
    else:
        print("Starting with 1 UTXO with balance %s" % balance)


# Given the max blocksize, current balance, and number of outputs available per tx
# how many txs, outputs, and individual balance to optimize spam to the maximum
def decider():
    confirmed_balance = rpc.getbalance('*', 1)
    # The max number of outputs in which you could make a 25 chain tx with the current balance
    amt_per_output = round(confirmed_balance / Decimal(MAX_OUTPUTS), 8)
    num_outputs_per_tx = MAX_OUTPUTS

    # Need each output to have at least enough btc to each make a chain
    # of 25 mempool transactions, each paying 1 sat/vbyte with
    # amounts above the dust limit
    if amt_per_output < TX_CHAIN_COST:
        num_outputs_per_tx = int(float(confirmed_balance) / TX_CHAIN_COST)
        amt_per_output = round(confirmed_balance / Decimal(num_outputs_per_tx), 8)

    print("Making transaction with %s outputs with %s btc" % (num_outputs_per_tx, amt_per_output))
    return num_outputs_per_tx, float(amt_per_output)


# Make single transaction splitting entire wallet balance between many outputs
def create_many_utxos(at_least_a_block=False):
    num_outputs_per_tx, amt_per_output = decider()
    print("This can take some time to generate...")
    addresses = [rpc.getnewaddress() for i in range(num_outputs_per_tx)]
    outputs = {addr: amt_per_output for addr in addresses}
    # Have to use -stdin because the number of outputs and addresses may be too large
    # for bash default arg limit
    send_many_args = ('', outputs, 1, '', addresses, False, 1008)
    formatted_input = '\n'.join(arg_to_cli(a) for a in send_many_args)
    txid = rpc('-datadir=%s' % DATA_DIR_SPAMMER, '-stdin', input=formatted_input).sendmany()
    # txid = rpc.sendmany("", outputs, 1, "making lots of outputs", addresses, False, 2)
    print("Transaction has txid %s" % txid)
    wait_for_confirmation()
    print("All txs are confirmed")


# Make chain of mempool transactions spending the previous
def make_spending_chain(utxo):
    global trigger_exit
    # Chain of 25 unspent outputs is the longest you can make
    for i in range(DEFAULT_ANCESTOR_LIMIT):
        to_send = float(round(utxo['amount'] - Decimal(DEFAULT_FEE), 8))
        if to_send < MIN_OUTPUT:
            # We have hit the dust threshold, so this should be our last loop
            trigger_exit = True
            break
        inputs = [{"txid": utxo["txid"], "vout": utxo["vout"]}]  # , "address": utxo["address"]}]
        to = rpc.getnewaddress()
        outputs = {to: to_send}
        # print("Spending %s and sending %s to %s" % (utxo['txid'], to_send, to))
        rawtx = rpc.createrawtransaction(inputs, outputs)
        signresult = rpc.signrawtransactionwithwallet(rawtx)
        txid = rpc.sendrawtransaction(signresult["hex"], False)
        # Set the next uxto to spend to be this transaction
        utxo = {'txid': txid, 'vout': 0, 'amount': Decimal(to_send)}


# function to be mapped over
def spam_parallel(utxos, threads=8):
    pool = ThreadPool(threads)
    pool.map(make_spending_chain, utxos)
    pool.close()
    pool.join()


# Spammers gonna spam
def start_spamming():
    while not trigger_exit:
        utxos = rpc.listunspent()
        if utxos:
            print("Creating 25 tx chains for %s utxos, this may take some time...." % len(utxos))
            spam_parallel(utxos)
            mempool = rpc.getmempoolinfo()
            print("Have mempool of %s transactions and %s MB" %
                  (mempool['size'], round(mempool['bytes'] / 1048576.0, 3)))
        wait_for_confirmation()
    print("All outputs have reached dust limit. Done!")


def doit():
    balance = rpc.getbalance('*', 1)
    assert balance > 0.01, "Need higher starting balance"
    # Get all coins in 1 UTXOs, don't actually need to this first
    consolidate()
    # Split UTXO to many even amount UTXOs
    create_many_utxos()
    # See if it works
    start_spamming()


trigger_exit = False
print_debug_info()
doit()
