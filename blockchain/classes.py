from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from time import time
from typing import List

from Cryptodome.Hash import SHA3_512
from Cryptodome.PublicKey import RSA
from Cryptodome.Signature import pkcs1_15

from blockchain.chain_settings import *


def valid_type(obj, *args):
    return type(obj).__name__ in args


#  stack overflow
def to_dict(obj, class_key=None):
    if isinstance(obj, dict):
        data = {}
        for (k, v) in obj.items():
            data[k] = to_dict(v, class_key)
        return data
    elif hasattr(obj, "_ast"):
        return to_dict(obj._ast())
    elif hasattr(obj, "__iter__") and not isinstance(obj, str):
        return [to_dict(v, class_key) for v in obj]
    elif hasattr(obj, "__dict__"):
        data = dict([(key, to_dict(value, class_key))
                     for key, value in obj.__dict__.items()
                     if not callable(value) and not key.startswith('_')])
        if class_key is not None and hasattr(obj, "__class__"):
            data[class_key] = obj.__class__.__name__
        return data
    else:
        return obj


def to_json(obj):
    return json.dumps(to_dict(obj), sort_keys=True)


def hasher(obj):
    """
    :return: SHA3_512 hasher object
    """
    assert valid_type(obj, 'Transaction', 'Block', 'bytes')
    return SHA3_512.new().update(obj if type(obj) == bytes else to_json(obj).encode())


@dataclass
class User:
    """
    This stores user variables and allows for easy data manipulation

    Attributes:

    """
    alias: str
    hashed_id: str
    public_key: str
    private_key: str

    def generate_key_pair(self):
        assert self.public_key is None, 'This user already has a public key'
        assert self.private_key is None, 'This user already has a private key'
        key_pair = RSA.generate(NUM_KEY_BITS)
        self.private_key = key_pair.export_key().decode()
        self.public_key = key_pair.publickey().export_key().decode()

    def sign(self, obj):
        """
        Only use for when you have the private key
        :param obj: Block or Transaction to sign
        """
        assert valid_type(obj, 'Transaction', 'Block')
        assert obj.signature is None, 'This Message is already signed'
        key = RSA.import_key(self.private_key)
        assert RSA.RsaKey.has_private(key), 'Invalid private key'
        signer = pkcs1_15.new(key)
        obj.signature = signer.sign(hasher(obj)).hex()

    def public_version(self):
        #  this will be used in various post-inits
        copy = deepcopy(self)
        copy.private_key = None
        return copy


def user_from_dict(user_dict):
    return User(alias=user_dict['alias'],
                hashed_id=user_dict['hashed_id'],
                public_key=user_dict['public_key'],
                private_key=user_dict['private_key'])


def valid_signature(obj):
    """
    :return: if the signature of the messages data is valid
    """
    assert valid_type(obj, 'Transaction', 'Block')
    assert obj.signature is not None, "This block hasn't been signed"
    if type(obj) == Transaction:
        sender = obj.sender
    else:
        sender = obj.miner
    public_key = RSA.import_key(sender.public_key)
    verifier = pkcs1_15.new(public_key)
    copy = deepcopy(obj)
    copy.signature = None
    try:
        verifier.verify(hasher(copy), bytearray.fromhex(obj.signature))
    except ValueError:
        return False
    return True


def timestamp():
    return datetime.utcfromtimestamp(time()).strftime('%Y-%m-%d %H:%M:%S')


@dataclass
class Transaction:
    """
    Class for storing transactions to allow for easy verification
    """
    sender: User
    recipient: User
    value: int
    fee: int
    time: str = None
    signature: str = None

    def __post_init__(self):
        self.sender = self.sender.public_version()
        self.recipient = self.recipient.public_version()
        if self.signature == 'None':
            self.signature = None
        if self.time == 'None':
            self.time = None
        if self.time is None:
            self.time = timestamp()

    def is_valid(self):
        if self.value < TRANSACTION_MIN_VALUE:
            return False
        if not valid_signature(self):
            return False
        sender_valid = False
        recipient_valid = False
        for user in USERS:
            p_k = user['public_key']
            if p_k == self.sender.public_key:
                sender_valid = True
            if p_k == self.recipient.public_key:
                recipient_valid = True
        return sender_valid and recipient_valid


def transaction_from_dict(transaction_dict):
    return Transaction(sender=user_from_dict(transaction_dict['sender']),
                       recipient=user_from_dict(transaction_dict['recipient']),
                       value=transaction_dict['value'],
                       fee=transaction_dict['fee'],
                       time=transaction_dict['time'],
                       signature=transaction_dict['signature'])


@dataclass
class Block:
    """
    Block class where the default constructor returns the genesis block
    """
    prev_hash: str
    miner: User
    transactions: List[Transaction]
    nonce: int = 0
    time: str = None
    signature: str = None

    def __post_init__(self):
        self.miner = self.miner.public_version()
        if self.time == 'None':
            self.time = None
        if self.time is None:
            self.time = timestamp()
        if self.nonce == '0':
            self.nonce = 0

    def transactions_valid(self):
        total = 0
        for transaction in self.transactions:
            if not transaction.is_valid():
                return False
            total += transaction.fee
        return total >= TOTAL_TRANSACTION_FEE

    def difficulty_valid(self, premade_json_str=None):
        for_mining = premade_json_str is not None
        if for_mining:
            h = hasher(premade_json_str.encode()).hexdigest()
        else:
            temp, self.signature = self.signature, None
            h = hasher(self).hexdigest()
            self.signature = temp
        return h[:DIFFICULTY] == '0' * DIFFICULTY

    def is_valid(self):
        """
        :return: if all the transactions are valid
                    and the hash has appropriate proof of work
        """
        if not self.difficulty_valid():
            return False
        if not self.transactions_valid():
            return False
        if not valid_signature(self):
            return False
        for user in USERS:
            p_k = user['public_key']
            if p_k == self.miner.public_key:
                return True
        return False

    def mine(self):
        assert self.transactions_valid(), 'You cannot mine an invalid block'
        assert self.nonce == 0, 'The nonce has already been modified'
        premade_json_str = to_json(self)
        nonce_str = '"nonce": '
        nonce_index = int(premade_json_str.find(nonce_str)) + len(nonce_str)
        nonce = 0
        while not self.difficulty_valid(premade_json_str):
            premade_json_str = premade_json_str[:nonce_index] + \
                               premade_json_str[nonce_index:].replace(str(nonce), str(nonce + 1), 1)
            nonce += 1
        self.nonce = nonce


def block_from_dict(block_dict):
    return Block(prev_hash=block_dict['prev_hash'],
                 miner=user_from_dict(block_dict['miner']),
                 transactions=[transaction_from_dict(transaction)
                               for transaction in block_dict['transactions']],
                 nonce=block_dict['nonce'],
                 time=block_dict['time'],
                 signature=block_dict['signature'])


@dataclass
class Blockchain:
    chain: List[Block] = None
    transactions: List[Transaction] = None

    def __post_init__(self):
        if self.chain is 'None':
            self.chain = None
        if self.transactions is 'None':
            self.transactions = None
        if self.transactions is None:
            self.transactions = []
        if self.chain is None:
            self.chain = []

    def compute_balances(self):
        users = dict()
        for user in USERS:
            users[user['public_key']] = user['initial_balance']
        for block in self.chain:
            reward = 0
            for transaction in block.transactions:
                if transaction.sender.public_key not in users:
                    users[transaction.sender.public_key] = -(transaction.value + transaction.fee)
                else:
                    users[transaction.sender.public_key] -= (transaction.value + transaction.fee)
                if transaction.recipient.public_key not in users:
                    users[transaction.recipient.public_key] = transaction.value
                else:
                    users[transaction.recipient.public_key] += transaction.value
                reward += transaction.fee
            if block.miner.public_key not in users:
                users[block.miner.public_key] = reward + BASE_MINER_REWARD
            else:
                users[block.miner.public_key] += reward + BASE_MINER_REWARD
        return users

    def is_valid(self):
        """
        :return: if all the blocks are valid,
                all the hash pointers are correct,
                all the users have a positive balance,
                all coinbase transactions are legitimate
        """
        genesis = self.chain[0]
        if not genesis.is_valid():
            return False
        prev_block = genesis
        for block in self.chain[1:]:
            if not block.is_valid():
                return False
            if hasher(prev_block).hexdigest() != block.prev_hash:
                return False
            prev_block = block
        return all([balance >= 0 for user, balance in self.compute_balances()])


def blockchain_from_dict(blockchain_dict):
    return Blockchain([block_from_dict(block)
                       for block in blockchain_dict['chain']],
                      [transaction_from_dict(transaction)
                       for transaction in blockchain_dict['transactions']])
