import requests
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime, timezone, timedelta
import streamlit as st
import plotly.graph_objects as go
import streamlit.components.v1 as components


######### FUNCTIONS ########
def get_token_details(address):
    url = f"https://explorer-api.lachain.network/api/v2/tokens/{address}"
    response = requests.get(url)

    data = response.json()
    token = {
        "name": data['name'],
        "symbol": data['symbol'],
        "decimals": data['decimals'],
        "holders": data['holders'],
        "address": data['address'],
        "total_supply": data['total_supply'],
        "decimals": int(data['decimals'])
    }

    return token

def fetch_txs_logs(lp):
    address = lp['address']
    url = f"https://explorer-api.lachain.network/api/v2/addresses/{address}/logs"
    response = requests.get(url)

    logs = response.json()['items']
    txs = []
    for log in logs:
        tx_hash = log["tx_hash"]
        block_number = log["block_number"]
        data = log["data"]
        topics = log["topics"]

        tx_exists = next((tx for tx in txs if tx["tx_hash"] == tx_hash), None)
        if tx_exists:
            tx_exists["logs"].append({
                "data": data,
                "topics": topics
            })
        else:
            txs.append({
                "tx_hash": tx_hash,
                "block_number": block_number,
                "logs": [{
                    "data": data,
                    "topics": topics
                }]
            })

    return txs

def process_onchain_logs(txs_logs, lp, LAC_USDC_trades):
    data_token = []
    buy_sell = 'buy'
    if lp['token_1']['symbol'] != 'WLAC' and lp['token_1']['symbol'] != 'UXD' and lp['token_1']['symbol'] != 'USDC' and lp['token_1']['symbol'] != 'USDT':
        txs_logs_token_1 = fetch_txs_logs(MATE_WLAC)
        data_token_1 = process_onchain_logs(txs_logs_token_1, MATE_WLAC, LAC_USDC_trades)

    for tx in txs_logs:
        block_datetime = string_to_datetime(get_datetime(tx['block_number']))
        token_0 = token_1 = volume_token_0 = volume_token_1 = None
        
        for log in tx['logs']:
            for topic in log['topics']:
                if topic == '0x1c411e9a96e071241c2f21f7726b17ae89e3cab4c78be50e062b03a9fffbbad1': # Sync
                    token_0, token_1, _ = hex_to_decimals(log['data'][2:],'Sync')
                if topic == '0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822': # Swap
                    volume_token_0, volume_token_1, buy_sell = hex_to_decimals(log['data'][2:],'Swap')
        
        if lp['token_1']['symbol'] == 'WLAC':
            nearest_trade = find_nearest_trade(LAC_USDC_trades, block_datetime)
            price = nearest_trade['price']
        elif lp['token_1']['symbol'] == 'UXD' or lp['token_1']['symbol'] == 'USDC' or lp['token_1']['symbol'] == 'USDT':
            price = 1
        else:
            price = search_price_token(data_token_1, block_datetime)
            

        if token_0 and token_1:
            new_data = {
                #"tx_hash": tx['tx_hash'],
                "datetime": block_datetime,
                "price": (token_1/10**lp['token_1']['decimals'] * price) / ((token_0/10**lp['token_0']['decimals'])),
                "volume": (volume_token_1/10**lp['token_0']['decimals']) * price if volume_token_1 else 0,
                "buy_sell": buy_sell
            }
            data_token.append(new_data)
    return data_token

def search_price_token(data_token, block_datetime):    
    nearest_record = None
    smallest_diff = float('inf')
    
    if isinstance(block_datetime, str):
        block_datetime = datetime.fromisoformat(block_datetime)

    for data in data_token:
        current_diff = abs((data['datetime'] - block_datetime).total_seconds())
        if current_diff < smallest_diff:
            smallest_diff = current_diff
            nearest_record = data
    
    if nearest_record:
        return nearest_record['price']
    else:
        return None
    
    
def get_datetime(block):
    url = f"https://explorer-api.lachain.network/api/v2/blocks/{block}"
    response = requests.get(url)

    return response.json()['timestamp']

def hex_to_decimals(hex_string, type):
    buy_sell = ''
    if len(hex_string) % 2 != 0:
        raise ValueError("Hexadecimal string length must be even.")

    if type == 'Swap':
        part1 = hex_string[:64]
        part2 = hex_string[64:128]
        part3 = hex_string[128:192]
        part4 = hex_string[192:256]
        if part1 != '0000000000000000000000000000000000000000000000000000000000000000':
            decimal1 = int(part1, 16)
            decimal2 = int(part4, 16)
            buy_sell = 'sell'
        else:
            decimal1 = int(part3, 16)
            decimal2 = int(part2, 16)
            buy_sell = 'buy'
    elif type == 'Sync':
        part1 = hex_string[:64]
        part2 = hex_string[64:]
        decimal1 = int(part1, 16)
        decimal2 = int(part2, 16)


    return decimal1, decimal2, buy_sell

def fetch_trades(pair):
    all_trades = []
    current_page = 1
    total_pages = 1  # Se asume al menos una pagina al iniciar

    while current_page <= total_pages:
        url = f"https://api.ripiotrade.co/v4/public/trades?pair={pair}&current_page={current_page}"
        response = requests.get(url)

        if response.status_code == 200:
            data = response.json()['data']
            all_trades.extend(data['trades'])
            total_pages = data['pagination']['total_pages']  # Se actualiza el total de paginas del response
            current_page += 1
        else:
            print(f"Failed to fetch page {current_page}. Status code: {response.status_code}")
            break

    return all_trades

def fetch_trades_LAC_UXD():
    LAC_trades = fetch_trades('LAC_USDC')
    #UXD_trades = fetch_trades('UXD_USDC')

    #return LAC_trades, UXD_trades
    return LAC_trades

def find_nearest_trade(pair_trades, target_datetime):
    all_trades = pair_trades
    
    if not all_trades:
        return None

    if isinstance(target_datetime, str):
        target_datetime = string_to_datetime(target_datetime)

    nearest_trade = None
    min_diff = float('inf')

    for trade in all_trades:
        trade_datetime = string_to_datetime(trade['date'])
        diff = abs((trade_datetime - target_datetime).total_seconds())
        
        if diff < min_diff:
            min_diff = diff
            nearest_trade = trade

    return nearest_trade

def string_to_datetime(date_string):
    if date_string.endswith('Z'):
        date_string = date_string[:-1]
        return datetime.strptime(date_string, '%Y-%m-%dT%H:%M:%S.%f').replace(tzinfo=timezone.utc)
    else:
        return datetime.strptime(date_string, '%Y-%m-%dT%H:%M:%S.%f')

def create_combined_graph(trades, token):
    df = pd.DataFrame(trades)
    df['date'] = df['datetime'].dt.date
    
    volume_df = df.groupby('date')['volume'].sum().reset_index()
    price_df = df.groupby('date')['price'].mean().reset_index()
    
    majority_trade = df.groupby(['date', 'buy_sell']).size().unstack(fill_value=0)
    majority_trade['majority'] = majority_trade.apply(lambda row: 'buy' if row['buy'] >= row['sell'] else 'sell', axis=1)
    
    volume_df = volume_df.merge(majority_trade[['majority']], on='date', how='left')
    volume_df['majority'] = volume_df.apply(lambda row: 'buy' if row['volume'] == 0 or row['majority'] == 0 else row['majority'], axis=1)

    fig = go.Figure()

    fig.add_trace(go.Bar(
        x=volume_df['date'], 
        y=volume_df['volume'], 
        name='Volumen', 
        yaxis='y', 
        marker=dict(color=volume_df['majority'].map({'buy': 'green', 'sell': 'red'})),
        hovertemplate='<b>Volumen</b>: %{y}<extra></extra>'
    ))

    fig.add_trace(go.Scatter(
        x=price_df['date'], 
        y=price_df['price'], 
        name='Precio', 
        yaxis='y2', 
        mode='lines+markers', 
        marker=dict(color='#ff7f0e'), 
        line=dict(color='#ff7f0e'),
        hovertemplate='<b>Precio</b>: %{y}<extra></extra>'
    ))

    fig.update_layout(
        title=f"{token}",
        xaxis=dict(
            title='Fecha',
            gridcolor='#444444',
            linecolor='#444444',
            showgrid=True,
            showline=True,
            zeroline=False
        ),
        yaxis=dict(
            title='Volumen',
            titlefont=dict(color='#1f77b4'),
            tickfont=dict(color='#1f77b4'),
            gridcolor='#444444',
            linecolor='#444444',
            showgrid=True,
            showline=True,
            zeroline=False,
            tickformat=','
        ),
        yaxis2=dict(
            title='Precio',
            titlefont=dict(color='#ff7f0e'),
            tickfont=dict(color='#ff7f0e'),
            anchor='x',
            overlaying='y',
            side='right',
            showgrid=False,
            zeroline=False,
            tickformat=','
        ),
        plot_bgcolor='#1e1e1e',
        paper_bgcolor='#1e1e1e',
        font=dict(color='#ffffff'),
        legend=dict(x=0, y=1.1, orientation='h'),
        hovermode='x unified'
    )

    return fig

def calculate_metrics(trades):
    df = pd.DataFrame(trades)
    
    # Get the last price
    if not df.empty:
        last_price = df.iloc[0]['price']
    else:
        last_price = 0

    now = datetime.now(timezone.utc)
    df['datetime'] = pd.to_datetime(df['datetime'], utc=True)
    last_24h = df[df['datetime'] >= (now - timedelta(hours=24))]
    last_24h_volume = last_24h['volume'].sum() if not last_24h.empty else 0

    return last_price, last_24h_volume

def display_metrics(last_price, last_24h_volume):
    col1, col2 = st.columns(2)
    
    with col1:
        st.metric(label="Precio", value=f"{last_price:.10f}")
        
    with col2:
        st.metric(label="Volumen 24h", value=f"{last_24h_volume:.3f}")


######### CONST ########
# Tokens
WLAC = get_token_details('0x2911a1AB18546cb501628Be8625C7503a2A7DB54')
MATE = get_token_details('0x10B9BE5482E9A16EFBD04be723E6452423FaD6fc')
UXD = get_token_details('0xDe09E74d4888Bc4e65F589e8c13Bce9F71DdF4c7')
XMATE = get_token_details('0x09762030148180BB2309364aB8F793443cf09823')

# LPs
XMATE_MATE = {
    "address": '0x211bbb315c9daa1900b435e8e7ddbcb1b6776702',
    "name": 'MATE-XMATE',
    "token_0": XMATE,
    "token_1": MATE
}
MATE_WLAC = {
    "address": '0xeb3fa9df542f8aff75d00fa486f891a56b5c8923',
    "name": 'MATE-WLAC',
    "token_0": MATE,
    "token_1": WLAC
}
MATE_UXD = {
    "address": '0x0c27280680bf3c8358630336949b08127ec15cb7',
    "name": 'MATE-UXD',
    "token_0": MATE,
    "token_1": UXD
}
WLAC_UXD_MATE = {
    "address": '0xcdc3736cabb8864eb1ef84b7583f9c1b1c9a118e',
    "name": 'WLAC-UXD',
    "token_0": WLAC,
    "token_1": UXD
}
WLAC_UXD_SAMBA = {
    "address": '0xc9cdb71fd82db58fff5e410c4e29e18c86b8b24d',
    "name": 'WLAC-UXD',
    "token_0": WLAC,
    "token_1": UXD
}

def prices_page():
    ###### PRELOAD #######
    LAC_USDC_trades = fetch_trades_LAC_UXD()

    ###### WEBSITE #######
    st.markdown("<h1 style='text-align: center;'>LaData - Precios & Volumen</h1>", unsafe_allow_html=True)
    fig = fig2 = None

    selection = st.selectbox('Selecciona un token', ['LAC', 'MATE', 'XMATE'])
    if selection == 'LAC':
        txs_logs = fetch_txs_logs(WLAC_UXD_MATE)
        data_token = process_onchain_logs(txs_logs, WLAC_UXD_MATE, LAC_USDC_trades)
        fig = create_combined_graph(data_token, WLAC_UXD_MATE['name'])
        price, last24hvolume = calculate_metrics(data_token)
        link_1 = f"[Compra en MateSwap](https://mateswap.xyz/es/swap?inputCurrency={WLAC_UXD_MATE['token_0']['address']}&outputCurrency={WLAC_UXD_MATE['token_1']['address']})"
        txs_logs_2 = fetch_txs_logs(WLAC_UXD_SAMBA)
        data_token_2 = process_onchain_logs(txs_logs_2, WLAC_UXD_SAMBA, LAC_USDC_trades)
        fig2 = create_combined_graph(data_token_2, WLAC_UXD_SAMBA['name'])
        link_2 = f"[Compra en SambaSwap](https://sambaswap.xyz/swap/es/swap?inputCurrency={WLAC_UXD_MATE['token_0']['address']}&outputCurrency={WLAC_UXD_MATE['token_1']['address']})"
        price_2, last24hvolume_2 = calculate_metrics(data_token_2)
    elif selection == 'MATE':
        txs_logs = fetch_txs_logs(MATE_WLAC)
        data_token = process_onchain_logs(txs_logs, MATE_WLAC, LAC_USDC_trades)
        fig = create_combined_graph(data_token, MATE_WLAC['name'])
        link_1 = f"[Compra en MateSwap](https://mateswap.xyz/es/swap?inputCurrency={MATE_WLAC['token_0']['address']}&outputCurrency={MATE_WLAC['token_1']['address']})"
        price, last24hvolume = calculate_metrics(data_token)
        txs_logs_2 = fetch_txs_logs(MATE_UXD)
        data_token_2 = process_onchain_logs(txs_logs_2, MATE_UXD, LAC_USDC_trades)
        fig2 = create_combined_graph(data_token_2, MATE_UXD['name'])
        link_2 = f"[Compra en MateSwap](https://mateswap.xyz/es/swap?inputCurrency={MATE_UXD['token_0']['address']}&outputCurrency={MATE_UXD['token_1']['address']})"
        price_2, last24hvolume_2 = calculate_metrics(data_token_2)
    elif selection == 'XMATE':
        txs_logs = fetch_txs_logs(XMATE_MATE)
        link_1 = f"[Compra en MateSwap](https://mateswap.xyz/es/swap?inputCurrency={XMATE_MATE['token_0']['address']}&outputCurrency={XMATE_MATE['token_1']['address']})"
        data_token = process_onchain_logs(txs_logs, XMATE_MATE, LAC_USDC_trades)
        fig = create_combined_graph(data_token, XMATE_MATE['name'])
        price, last24hvolume = calculate_metrics(data_token)

    display_metrics(price,last24hvolume)
    st.markdown(link_1)
    st.plotly_chart(fig)
    if fig2:
        display_metrics(price_2,last24hvolume_2)
        st.markdown(link_2)
        st.plotly_chart(fig2)

def home():
    st.title('LaData')
    st.subheader('Tu hub de información para todo lo relacionado con la blockchain LaChain.')
    st.write('')
    st.write('')
    st.write('¿Querés colaborar? Hace una donación en cualquier red a `0x8CE8ce3C36F107461D9dd0AaC367Be8f53d8C643`')
    st.write('Más info de cómo fue creado LaData en [Bloque X](https://bloquex.me/)')
    st.write('Webmaster (?): Fernando Molina - [@fergmolina](https://linktr.ee/fergmolina)')

def display_section(items):
    for item in items:
        with st.container():
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(f"**{item['name']}**")
                link = f"https://explorer.lachain.network/address/{item['address']}"
                st.write(f"Address: `{item['address']}`")
                st.markdown(f"Explorer: [LaChain Explorer]({link})")
                if "url" in item:
                    st.markdown(f"URL: [{item['url']}]({item['url']})")
            with col2:
                st.image(item['image_url'], width=50)

def tokens():
    st.title("Tokens")

    tokens = [
        {"name": "WLAC", "address": "0x2911a1AB18546cb501628Be8625C7503a2A7DB54", "image_url": "https://raw.githubusercontent.com/mateswap-fi/icons/master/token/lac.png"},
        {"name": "UXD", "address": "0xDe09E74d4888Bc4e65F589e8c13Bce9F71DdF4c7", "image_url": "https://raw.githubusercontent.com/mateswap-fi/icons/master/token/uxd.png"}, 
        {"name": "USDT", "address": "0x7dC8b9e3B083C26C68f0B124cA923AaEc7FBee39", "image_url": "https://raw.githubusercontent.com/mateswap-fi/assets/master/blockchains/lachain/assets/0x7dC8b9e3B083C26C68f0B124cA923AaEc7FBee39/logo.png"},
        {"name": "USDC", "address": "0x51115241c7b8361EeE88D8610f71d0A92cee5323", "image_url": "https://raw.githubusercontent.com/mateswap-fi/assets/master/blockchains/lachain/assets/0x51115241c7b8361EeE88D8610f71d0A92cee5323/logo.png"},
        {"name": "WETH", "address": "0x42C8C9C0f0A98720dACdaeaC0C319cb272b00d7E", "image_url": "https://raw.githubusercontent.com/mateswap-fi/assets/master/blockchains/lachain/assets/0x42C8C9C0f0A98720dACdaeaC0C319cb272b00d7E/logo.png"},
        {"name": "MATE", "address": "0x10B9BE5482E9A16EFBD04be723E6452423FaD6fc", "image_url": "https://raw.githubusercontent.com/mateswap-fi/icons/master/token/mate.png"},
        {"name": "XMATE", "address": "0x09762030148180BB2309364aB8F793443cf09823", "image_url": "https://raw.githubusercontent.com/mateswap-fi/assets/master/blockchains/lachain/assets/0x09762030148180BB2309364aB8F793443cf09823/logo.png"}

    ]

    display_section(tokens)

def dexs():
    st.title("Dexs")

    dexs = [
        {"name": "MateSwap", "url": "https://mateswap.xyz/", "address": "0x12D9CC71b28B70d08f28CCf92d9Ab1D8400f97bD", "image_url": "https://raw.githubusercontent.com/mateswap-fi/icons/master/token/mate.png"},
        {"name": "SambaSwap", "url": "https://sambaswap.xyz/", "address": "0xCEaB4e71463c643B7E5776D14995D8015e1Fa14b", "image_url": "https://sambaswap.xyz/static/media/logo.f3300214.webp"}
    ]

    display_section(dexs)

def bridges():
    st.title("Bridges")

    bridges = [
        {"name": "LaChain Bridge", "url":"https://bridge.lachain.network/","address": "0x000000000000000", "image_url": "https://www.cripto247.com/.image/c_limit%2Ccs_srgb%2Cq_auto:good%2Cw_700/MTk5OTE5MzIwNzMyNjczMTI3/lachain.webp"},
    ]

    display_section(bridges)

def google_analytics(tracking_id):
    html_template = f"""
    <script async src="https://www.googletagmanager.com/gtag/js?id={tracking_id}"></script>
    <script>
      window.dataLayer = window.dataLayer || [];
      function gtag(){{dataLayer.push(arguments);}}
      gtag('js', new Date());
      gtag('config', '{tracking_id}');
    </script>
    """
    components.html(html_template, height=0, width=0)

#### LOADING WEBSITE ####

st.set_page_config(
    page_title='LaData - LaChain info',  
    page_icon='🔗',  
    initial_sidebar_state='expanded'  
)


google_analytics('G-0ETCQEHLL0')

st.sidebar.title("Menu")
if st.sidebar.button("Home"):
    st.session_state['current_page'] = 'home'
if st.sidebar.button("Precios y Volumen"):
    st.session_state['current_page'] = 'prices'
if st.sidebar.button("Tokens"):
    st.session_state['current_page'] = 'tokens'
if st.sidebar.button("DEXs"):
    st.session_state['current_page'] = 'dexs'
if st.sidebar.button("Bridges"):
    st.session_state['current_page'] = 'bridges'

current_page = st.session_state.get('current_page', 'home')

if current_page == 'home':
    home()
elif current_page == 'prices':
    prices_page()
elif current_page == 'tokens':
    tokens()
elif current_page == 'dexs':
    dexs()
elif current_page == 'bridges':
    bridges()