"""Read-only dashboard for the broker-disconnected Moneybot paper engine."""
import os
import streamlit as st
import pandas as pd
from agent.engine import PaperEngine

st.set_page_config(page_title='Moneybot Paper Dashboard', layout='wide')
st.title('Moneybot — Paper Trading Dashboard')
st.caption('Simulation only. This dashboard does not submit broker orders or run the worker.')
path = os.getenv('DB_PATH', 'data/moneybot.sqlite3')
if not os.getenv('DATABASE_URL') and not os.path.exists(path):
    st.info('No paper journal yet. Start the separate paper worker with persistent storage to generate results.')
    st.stop()
engine = PaperEngine(path, database_url=os.getenv('DATABASE_URL'))
cash, positions, events = engine.snapshot()
positions_df = pd.DataFrame(positions, columns=['symbol','entry','qty','stop','target','entry_ts'])
realized = float(events.loc[events.kind == 'EXIT', 'pnl'].sum()) if not events.empty else 0.0
c1,c2,c3,c4 = st.columns(4)
c1.metric('Cash', f'${cash:,.2f}')
c2.metric('Realized P&L (recent 250 events)', f'${realized:,.2f}')
c3.metric('Open positions', len(positions))
c4.metric('Mode', 'PAPER ONLY')
st.subheader('Open virtual positions')
st.dataframe(positions_df, use_container_width=True, hide_index=True)
st.subheader('Recent paper events')
st.dataframe(events, use_container_width=True, hide_index=True)
st.warning('Prices and P&L are simplified simulated fills, not executable market quotes. Results exclude commissions, slippage and other costs. Realized P&L metric is limited to the 250 displayed events.')
