#import modules
from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract
import pandas
import threading
import time

#define connection variables
twsIP = '127.0.0.1'
twsPort = 7497
apiId = 1

#define IB API class
class IBapi(EWrapper, EClient):
	def __init__(self):
		EClient.__init__(self, self)
		self.data = [] #Initialize variable to store candle

	def historicalData(self, reqId, bar):
		print(f'Time: {bar.date} Close: {bar.close}')
		self.data.append([bar.date, bar.close])

#define run loop function
def run_loop():
	app.run()

#create new app IBapi object and connect to API
app = IBapi()
app.connect(twsIP, twsPort, apiId)

#Start the socket in a thread
api_thread = threading.Thread(target=run_loop, daemon=True)
api_thread.start()

time.sleep(1) #Sleep interval to allow time for connection to server

#Create contract object
SPY_contract = Contract()
SPY_contract.symbol = 'SPY'
SPY_contract.secType = 'STK'
SPY_contract.exchange = 'ISLAND'
SPY_contract.currency = 'USD'

#Request historical candles
app.reqHistoricalData(1, SPY_contract, '', '4 W', '10 mins', 'BID', 0, 2, False, [])

time.sleep(5) #sleep to allow enough time for data to be returned

df = pandas.DataFrame(app.data, columns=['DateTime', 'Close'])
df['DateTime'] = pandas.to_datetime(df['DateTime'],unit='s')
df.to_csv('EURUSD_Hourly.csv')

print(df)

app.disconnect()
