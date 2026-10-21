import meshtastic
import meshtastic.serial_interface
from pubsub import pub
import time
import random
import string
from pocketbase import PocketBase
from datetime import datetime, timedelta, timezone
import base58
from solana.rpc.api import Client
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import TransferParams, transfer
from solders.transaction import Transaction
from solders.message import Message

# --- CONFIGURATION ---
POCKETBASE_URL = "https://pocketbase-production-2285.up.railway.app"
pb = PocketBase(POCKETBASE_URL)

# --- SOLANA CONFIGURATION ---
SOLANA_RPC_URL = "https://api.devnet.solana.com" # Devnet for testing
solana_client = Client(SOLANA_RPC_URL)

# REPLACE THIS WITH YOUR TREASURY PRIVATE KEY (Base58)
TREASURY_PRIVATE_KEY = "3EVJfeTqS4VbpmUsTWVJda1tfhrTWSXeMEunFBAGDzCMhVMzmhYVzm5SLddaZWFNb9dg8ozK22v3fcfLnavA3MeY"
treasury_keypair = Keypair.from_bytes(base58.b58decode(TREASURY_PRIVATE_KEY))
print(f"Treasury Wallet: {treasury_keypair.pubkey()}")

# How much SOL to airdrop per request (0.001 SOL)
AIRDROP_AMOUNT = 1000000 

REGIONS = {
    "JAPAN": { "puzzle_id": "puzzle-japan", "prefix": "JPN" },
    "USA": { "puzzle_id": "puzzle-usa", "prefix": "USA" },
    "EUROPE": { "puzzle_id": "puzzle-europe", "prefix": "EUR" },
    "CHINA": { "puzzle_id": "puzzle-china", "prefix": "CHN" },
    "AFRICA": { "puzzle_id": "puzzle-africa", "prefix": "AFR" },
    "AUSTRALIA": { "puzzle_id": "puzzle-australia", "prefix": "AUS" },
    "SA": { "puzzle_id": "puzzle-sa", "prefix": "SAM" },
    "RUSSIA": { "puzzle_id": "puzzle-russia", "prefix": "RUS" },
    "INDIA": { "puzzle_id": "puzzle-india", "prefix": "IND" },
    "ARCTIC": { "puzzle_id": "puzzle-arctic", "prefix": "ARC" },
    "ANTARCTICA": { "puzzle_id": "puzzle-antarctica", "prefix": "ANT" },
    "ME": { "puzzle_id": "puzzle-me", "prefix": "MID" },
    "OCEANIA": { "puzzle_id": "puzzle-oceania", "prefix": "OCE" },
    "NA": { "puzzle_id": "puzzle-na", "prefix": "NAR" },
    "CA": { "puzzle_id": "puzzle-ca", "prefix": "CAM" }
}

def generate_code(prefix):
    digits = ''.join(random.choices(string.digits, k=4))
    return f"{prefix}-{digits}"

def send_sol_airdrop(recipient_wallet):
    try:
        recipient_pubkey = Pubkey.from_string(recipient_wallet)
        
        # Create transfer instruction
        transfer_ix = transfer(
            TransferParams(
                from_pubkey=treasury_keypair.pubkey(),
                to_pubkey=recipient_pubkey,
                lamports=AIRDROP_AMOUNT
            )
        )
        
        # Get recent blockhash
        recent_blockhash = solana_client.get_latest_blockhash().value.blockhash
        
        # Create and sign transaction
        msg = Message.new_with_blockhash([transfer_ix], treasury_keypair.pubkey(), recent_blockhash)
        txn = Transaction.new_unsigned(msg)
        txn.sign([treasury_keypair], recent_blockhash)
        
        # Send transaction
        result = solana_client.send_transaction(txn)
        print(f"✅ AIRDROP SUCCESS: https://explorer.solana.com/tx/{result.value}?cluster=devnet")
        return True
    except Exception as e:
        print(f"❌ AIRDROP FAILED: {e}")
        return False

def onReceive(packet, interface):
    try:
        if 'decoded' in packet and packet['decoded']['portnum'] == 'TEXT_MESSAGE_APP':
            message = packet['decoded']['text'].upper()
            sender = packet['fromId']
            
            print(f"\nReceived from {sender}: {message}")
            
            if message.startswith("REQ "):
                region_key = message.replace("REQ ", "").strip()
                
                if region_key in REGIONS:
                    region = REGIONS[region_key]
                    
                    # Look up the linked wallet
                    wallet = "UNLINKED"
                    try:
                        links = pb.collection('mesh_links').get_full_list(
                        query_params={"filter": f"node_id='{sender}'"}
                        )

                        if len(links) > 0:
                            wallet = links[0].wallet
                            print(f"Found linked wallet: {wallet}")
                    except Exception as e:
                        print(f"Link Lookup Error: {e}")

                    # Generate the dynamic code
                    new_code = generate_code(region["prefix"])
                    expires = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
                    
                    # Save lease to PocketBase
                    try:
                        pb.collection('mesh_leases').create({
                            "wallet": wallet, 
                            "puzzle_id": region["puzzle_id"],
                            "lease_code": new_code,
                            "expires_at": expires
                        })
                        
                        # Send the code back over radio
                        response = f"CODE: {new_code}. EXPIRES IN 5 MIN."
                        interface.sendText(response, destinationId=sender)
                        print(f"Leased {new_code} for {region_key} to {wallet}")
                        
                        # TRIGGER AIRDROP if wallet is linked
                        if wallet != "UNLINKED":
                            print(f"Initiating Solana airdrop to {wallet}...")
                            send_sol_airdrop(wallet)
                        
                    except Exception as e:
                        print(f"Database Error: {e}")
                        interface.sendText("ERROR: MESH SERVER OFFLINE.", destinationId=sender)
                
    except Exception as e:
        print(f"Error: {e}")

# Connect to radio
try:
    interface = meshtastic.serial_interface.SerialInterface(devPath='COM4')
    my_info = interface.getMyNodeInfo()
    print(f"=== LAPTOP DEVICE ID: {my_info['user']['id']} ===")
    print(f"=== LAPTOP DEVICE NAME: {my_info['user']['longName']} ===")
except Exception as e:
    print(f"Could not connect to COM4. Error: {e}")
    exit()

pub.subscribe(onReceive, "meshtastic.receive")
print("Mesh DHCP Server Online. Awaiting 'REQ [REGION]' commands...")

while True:
    time.sleep(1)