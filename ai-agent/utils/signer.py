import hmac,hashlib,base64

def sign(secret,msg):
    sig = hmac.new(secret.encode(),msg.encode(),hashlib.sha256).digest()
    return base64.b64encode(sig).decode()
