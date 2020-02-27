#!/usr/bin/env python3
import argparse
import decimal
from decimal import Decimal
from multiprocessing.dummy import Pool as ThreadPool
import os
from rpc import NodeCLI, arg_to_cli
from subprocess import CalledProcessError
import sys
import time


def print_debug_info(args):
    print("----------- Runtime Settings -----------")
    print("Using chain %s with feerate %s sat/byte" % (args.chain, args.feerate))
    print("A one input -> one output tx is %s bytes" % SIZE_OF_1_TO_1_TX)
    print("Default fee per tx is %s sat" % int(DEFAULT_FEE * COIN))
    print("Max number of outputs per tx is %s, and max number of inputs is %s" % (MAX_OUTPUTS, MAX_INPUTS))
    print("The cost to make a chain of 25 mempool txs is %s satoshis" % int(TX_CHAIN_COST * COIN))
    print("A chain of 25 txs for %s outputs is %s MB" % (MAX_OUTPUTS, SPAM_SIZE_PER_OUTPUT_SET / 1000000))
    print("----------------------------------------\n\n")


# Get satoshis from decimal btc amount
def sat(amt):
    return amt * COIN


# Wait until all our spent coins are confirmed
def wait_for_confirmation(txs_to_confirm=1):
    while len(rpc.listunspent()) < txs_to_confirm:
        if REGTEST:
            try:
                addr = miner.getnewaddress()
                miner.generatetoaddress(1, addr)
            except Exception:
                miner.generate(1)
            time.sleep(3)
        else:
            time.sleep(60)
        print("Waiting for confirmation of one or more txs...")


def make_stdinput(*args):
    return '\n'.join(arg_to_cli(a) for a in args)


# Consolidate all balance into single utxo before start splitting
def consolidate():
    # First check for unconfirmed deposits
    utxos = rpc.listunspent(0)
    num_unspent = len(utxos)
    wait_for_confirmation(num_unspent)
    if num_unspent > 1:
        if num_unspent > MAX_INPUTS:
            consolidation_txs = int(num_unspent / MAX_INPUTS) + 1
            print("Have %s outputs that can be consolididated into %s transactions" % (num_unspent, consolidation_txs))
            for i in range(consolidation_txs):
                to_add = utxos[i*MAX_INPUTS:(i+1)*MAX_INPUTS]
                inputs = [{'txid': u['txid'], 'vout': u['vout']} for u in to_add]
                amt = round(float(sum(i['amount'] for i in to_add)) - (STD_TX_SIZE_LIMIT / COIN), 8)
                outputs = {rpc.getnewaddress(): amt}
                if REGTEST:
                    rawtx = rpc('-datadir=%s' % DATA_DIR_SPAMMER,
                                '-stdin',
                                input=make_stdinput(inputs, outputs)).createrawtransaction()
                    signresult = rpc('-datadir=%s' % DATA_DIR_SPAMMER,
                                     '-stdin',
                                     input=make_stdinput(rawtx)).signrawtransactionwithwallet()
                    txid = rpc('-datadir=%s' % DATA_DIR_SPAMMER,
                               '-stdin',
                               input=make_stdinput(signresult['hex'])).sendrawtransaction()
                else:
                    rawtx = rpc('-stdin', input=make_stdinput(inputs, outputs)).createrawtransaction()
                    signresult = rpc('-stdin', input=make_stdinput(rawtx)).signrawtransactionwithwallet()
                    txid = rpc('-stdin', input=make_stdinput(signresult['hex'])).sendrawtransaction()
                print("Transaction has txid %s" % txid)
            wait_for_confirmation(txs_to_confirm=consolidation_txs)

        balance = rpc.getbalance('*', 1)
        father_of_spam = rpc.getnewaddress()
        print("Aggregating all coins to %s" % father_of_spam)
        # Subtract fee from entire amount with conf target of one week, which should
        # be close to 1 sat / byte

        if CHAIN_TO_USE in ('BTC', 'BSV'):
            rpc.sendtoaddress(father_of_spam, balance, "", "", True, False, 1008)
        else:
            rpc.sendtoaddress(father_of_spam, balance, "", "", True)
        wait_for_confirmation()
        print("Sent all %s coins to %s" % (balance, father_of_spam))
    else:
        balance = rpc.getbalance('*', 1)
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

    return num_outputs_per_tx, float(amt_per_output)


# Make single transaction splitting entire wallet balance between many outputs
def create_many_utxos(at_least_a_block=False):
    num_outputs_per_tx, amt_per_output = decider()
    print("Making transaction with %s outputs with %s btc, which can take some time..." %
          (num_outputs_per_tx, amt_per_output))
    addresses = [rpc.getnewaddress() for i in range(num_outputs_per_tx)]
    outputs = {addr: amt_per_output for addr in addresses}
    # Have to use -stdin because the number of outputs and addresses may be too large
    # for bash default arg limit
    if CHAIN_TO_USE in ('BTC', 'BSV'):
        send_many_args = ('', outputs, 1, '', addresses, False, 1008)
    else:
        send_many_args = ('', outputs, 1, '', addresses)
    formatted_input = '\n'.join(arg_to_cli(a) for a in send_many_args)
    if REGTEST:
        txid = rpc('-datadir=%s' % DATA_DIR_SPAMMER, '-stdin', input=formatted_input).sendmany()
    else:
        txid = rpc('-stdin', input=formatted_input).sendmany()
    # txid = rpc.sendmany("", outputs, 1, "making lots of outputs", addresses, False, 2)
    print("Transaction has txid %s" % txid)
    wait_for_confirmation()


# Make chain of mempool transactions spending the previous
def make_spending_chain(utxo):
    # Chain of 25 unspent outputs is the longest you can make
    to = rpc.getnewaddress()
    for i in range(DEFAULT_ANCESTOR_LIMIT):
        to_send = float(round(utxo['amount'] - Decimal(DEFAULT_FEE), 8))
        if to_send < MIN_OUTPUT:
            # We have hit the dust threshold, so this should be our last loop
            break
        inputs = [{"txid": utxo["txid"], "vout": utxo["vout"]}]
        outputs = {to: to_send}
        # print("Spending %s and sending %s to %s" % (utxo['txid'], to_send, to))
        try:
            rawtx = rpc.createrawtransaction(inputs, outputs)
            signresult = rpc.signrawtransactionwithwallet(rawtx)
            if CHAIN_TO_USE in ('BTC', 'BSV'):
                txid = rpc.sendrawtransaction(signresult["hex"], 0)
            else:
                txid = rpc.sendrawtransaction(signresult["hex"], False)

        except Exception as e:
            print("Had a problem making chain, %s, breaking..." % str(e))
            break
        # Set the next uxto to spend to be this transaction
        utxo = {'txid': txid, 'vout': 0, 'amount': Decimal(to_send)}


# Make a thread pool to chug through the passed utxo list and go to town
# but because of python's GIL it's not really all that parallel but better than
# usual because rpc commands spawn separate processes. Right?
def spam_parallel(utxos, numthreads):
    pool = ThreadPool(numthreads)
    pool.map(make_spending_chain, utxos)
    pool.close()
    pool.join()


# Spammers gonna spam
def start_spamming(onepass=False, numthreads=4):
    init_set_size = len(rpc.listunspent())
    while True:
        unspent = rpc.listunspent()
        utxos_above_dust = [u for u in unspent if u['amount'] > (MIN_OUTPUT + DEFAULT_FEE)]
        num_dust = len(unspent) - len(utxos_above_dust)
        if utxos_above_dust:
            print("Creating chain of 25 txs for %s utxos with %s threads, this may take some time...." %
                  (len(utxos_above_dust), numthreads))
            spam_parallel(utxos_above_dust, numthreads)
            mempool = rpc.getmempoolinfo()
            print("Have mempool of %s transactions and %s MB" %
                  (mempool['size'], round(mempool['bytes'] / 1048576.0, 3)))
        elif len(unspent) == init_set_size and not utxos_above_dust:
            print("All outputs have reached dust limit!")
            break

        # If no utxos have reached the dust limit yet, we can just wait for next confirmed tx
        # until we start spamming again, otherwise just sleep until a new one that hasn't hit
        # dust limit is confirmed
        print("%s utxos have reached dust limit, %s remaining " % (num_dust, init_set_size - num_dust))

        if onepass:
            print("Finished one pass of spamming")
            break

        wait_for_confirmation(num_dust + 1)


def doit(args):
    # Get all coins in 1 UTXOs, don't actually need to this first
    consolidate()
    # Split UTXO to many even amount UTXOs
    create_many_utxos()
    # See if it works
    start_spamming(onepass=args.onepass, numthreads=args.numthreads)


description = """Spam a bitcoin chain with cheap transactions.

    By default the program will:

    1. Consolidate the entire balance into one UTXO (consolidation). This step is skipped
       if the balance is already consolidated
    2. Split the entire balance into as many UTXOs as possible in a single transaction (split)
    3. Take each UTXO and create chains of dependent txs submitted to the mempool in a loop
       until the program is terminated or the dust limit has been reached on all utxos"""


# Parse arguments and pass through unrecognised args
parser = argparse.ArgumentParser(add_help=True,
                                 usage='%(prog)s [options]',
                                 description=description,
                                 formatter_class=argparse.RawTextHelpFormatter)
parser.add_argument('--chain', default='BTC', help='Choose fork: "BTC", "BCH", or "BSV" (default: "BTC")')
parser.add_argument('--feerate', type=int, default=1, help='Chose fee-rate for spam in sat/byte (default: 1)')
parser.add_argument('--numthreads', type=int, default=4, help='Chose the number of spam threads (default: 4)')
parser.add_argument('--datadir', action='store', help='Set if custom datadir should be used')
parser.add_argument('--live',
                    action='store_true',
                    help='If supplied, will submit spam to local bitcoin node, rather than regtest nodes')
parser.add_argument('--only_consolidate',
                    action='store_true',
                    help="Only consolidate entire balance back into 1 UTXO. This can be called after spamming.")
parser.add_argument('--only_split',
                    action='store_true',
                    help="Only Split balance into many UTXOs.")
parser.add_argument('--only_spam',
                    action='store_true',
                    help="Start spamming on all existing UTXOs.")
parser.add_argument('--onepass',
                    action='store_true',
                    help="Only do one pass of spamming (instead of loop)")

args, unknown_args = parser.parse_known_args()

if args.chain.upper() not in ('BTC', 'BCH', 'BSV'):
    print("Invalid --chain choice: %s" % args.chain)
    sys.exit(0)

if unknown_args:
    print("Unknown args: %s...Try" % unknown_args)
    print("./spam.py --help")
    sys.exit(0)

# Round down to 8 places for satoshis calcs
decimal.getcontext().rounding = decimal.ROUND_DOWN

# 1 BTC = 10^8 statoshis
COIN = 10**8
# Dust limit for p2pkh
MIN_OUTPUT = 546 / COIN
# Max standard tx size is 100k bytes / vbytes
STD_TX_SIZE_LIMIT = 100000
# The mempool will allow a tx to have at most 25 ancestors before rejecting entry
DEFAULT_ANCESTOR_LIMIT = 25
# Dirs for regtest data
DATA_DIR_SPAMMER = "./spamdir/"
DATA_DIR_MINER = "./minerdir/"

# If using segwit native addr (bech32), calculate vbytes, otherwise assuming using
# standard p2pkh transactions
SEGWIT = (args.chain == 'BTC' and args.live)

# Get tx size estimate
if SEGWIT:
    # Segwit get dat discount
    def guess_sz(num_in, num_out):
        return num_in*68.5 + num_out*31 + 10.5
else:
    # P2PKH still got dat lame bytes
    def guess_sz(num_in, num_out):
        return num_in*148 + num_out*34 + 10

# Use btc by default, but can change
CHAIN_TO_USE = args.chain.upper()
if CHAIN_TO_USE == 'BTC':
    # MAX blocksize for BTC in vbytes
    MAX_BLOCK = 1000000
elif CHAIN_TO_USE == 'BCH':
    # MAX blocksize for BCH in bytes
    MAX_BLOCK = 32000000
elif CHAIN_TO_USE == 'BSV':
    # MAX blocksize for BSV in bytes
    MAX_BLOCK = 128000000


# want 1 sat/byte for a 1 input to 1 output tx
SIZE_OF_1_TO_1_TX = guess_sz(1, 1)
# Want to pay 1 sat/vbyte
DESIRED_FEE_PER_BYTE = int(args.feerate)
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
    MAX_INPUTS = int((STD_TX_SIZE_LIMIT - 41) / 68.5)
else:
    MAX_OUTPUTS = int((STD_TX_SIZE_LIMIT - 400) / 34)
    MAX_INPUTS = int((STD_TX_SIZE_LIMIT - 44) / 148)


# Going to make txs with max number of outputs that can all be independently chained in mempool
# If the entire set is less than a block you can can make multiple MAX_OUTPUT txs
SPAM_SIZE_PER_OUTPUT_SET = (DEFAULT_ANCESTOR_LIMIT * MAX_OUTPUTS * SIZE_OF_1_TO_1_TX)

REGTEST = not args.live

# Finally setup the RPC objects
if REGTEST:
    rpc = NodeCLI(os.getenv("BITCOINCLI", "bitcoin-cli"), datadir=DATA_DIR_SPAMMER)
    miner = NodeCLI(os.getenv("BITCOINCLI", "bitcoin-cli"), datadir=DATA_DIR_MINER)
else:
    if args.datadir:
        rpc = NodeCLI(os.getenv("BITCOINCLI", "bitcoin-cli"), datadir=args.datadir)
    else:
        rpc = NodeCLI(os.getenv("BITCOINCLI", "bitcoin-cli"))


# See if the rpc is callable
try:
    rpc.help()
except CalledProcessError:
    print("Cannot run bitcoin-cli either because bitcoind is not running or datadir is not found.")
    print("Exiting...")
    sys.exit(0)

print_debug_info(args)

if args.only_consolidate:
    consolidate()
elif args.only_split:
    create_many_utxos()
elif args.only_spam:
    start_spamming(onepass=args.onepass, numthreads=args.numthreads)
else:
    doit(args)

print("Done!")
