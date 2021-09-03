#!/usr/bin/env python3
"""
IBKR TWS API Trading Algorithm
Author: Derrick Ike
Version: 1.0
Date: 6 June 2021
######################

check if there are open orders/positions
check price of VIX
check price of SPX
find next trading date
get options chain
find strike @15-20 delta
calculate available margin & determine dollar value of 25% rounded to nearest $500
create combo order
submit order @ bid price
modify order to mid-price and wait 5s (repeat until filled)
"""

#import modules
from ibapi.client import EClient
from ibapi.wrapper import EWrapper
import sys

sys.path.append('/home/')

# types
from ibapi.common import * # @UnusedWildImport
from ibapi.order_condition import * # @UnusedWildImport
from ibapi.contract import *
from ibapi.order import *
from ibapi.order_state import * # @UnusedWildImport
from ibapi.execution import Execution
from ibapi.execution import ExecutionFilter
from ibapi.commission_report import CommissionReport
from ibapi.tag_value import TagValue
from twsapi import IBapi

import enum
import pandas as pd
import threading
import time
import datetime
import itertools
import pprint
import copy
from secrets import AppConfig


#Get current timestamp
def getTimeNow():
	timeNow = datetime.datetime.now().strftime("%d%b%y_%H%M%S_%f")
	return timeNow

#define connection variables
# TWS_IP = '127.0.0.1'
# TWS_PORT = 7497
# API_ID = 1
# ACCOUNT_NUMBER = 'DU2645159'

appConfig = AppConfig()

#define other program variables
checkTradingHours = True
reqUID = 1000
vixFlag = 0
optMaxDTE = 5
optMinDTE = 1
activeReqs = []
activeOrders = []
targetFactor = 1
nStrikes = 45
targetDelta = -0.15
precision = 0.015
backtestFlag = False
requestDelay = 1
loopDelay = 30
# orderFilled = False
# orderMod = False
lastParentId = 0
# lastOrderPrice = 0
# modAttempt = 1
...
print('\n\n####################################\n'
,getTimeNow(),
'\n####################################\n')

class ReqUid():
	iter = itertools.count(1000,1)
	def __init__(self):
		self.id = next(self.iter)

class OptionGreeks():
	def __init__(self, c, priceTarget):
		self.c = c
		self.optC = copy.copy(c)
		self.optC.lastTradeDateOrContractMonth = None
		self.underCID = None
		self.requestDelay = 0.5
		self.exps = []
		self.strikes = []
		self.nStrikes = 45
		self.optGreeks = []
		self.DTE = 0
		self.conEXpDate = None
		self.tradingClass = None
		self.priceTarget = priceTarget
		# self.tradeMargin = tradeSize()[0]

	def getConID(self):
		#request contract details to get contract ID
		print(f'Request {self.c.symbol} contract details')
		try:
			app.deets = []
			app.reqContractDetails(getReqID(), self.c)
			time.sleep(1)
			contractDetailsDF = pd.DataFrame(app.deets, columns=['ReqID','ConID','Symbol','LastTradeDate','Strike','Right','UnderlyingContractID'])
			print(f'Contract Detail request for {self.c.symbol} \n', contractDetailsDF)
			self.underCID = app.deets[0][6]
			conID = app.deets[0][1]
			if (self.c.secType == 'STK') or (self.c.secType == 'IND'):
				self.underCID = conID
		except:
			print('Contract Details Request Failed')

		self.getOptionsChain()

	def getOptionsChain(self):
		#Reqeust options chain
		print(f'Request {self.optC.symbol} options chain')
		self.optGreeks = []
		try:
			app.reqSecDefOptParams(getReqID(), self.optC.symbol, "", self.optC.secType, self.underCID)
			time.sleep(self.requestDelay)
			# c = copy.copy(c)
			self.optC.secType = 'OPT'
			self.optC.right = 'P'
			today = datetime.datetime.now()
			#get options expirations for CBOE exchange only
			#app.optParams: ([0:reqID, 1:exchange, 2:underlyingConId, 3:tradingClass, 4:multiplier, 5:expirations, 6:strikes])
			self.exps = []
			expSet = []
			self.strikes = []
			strikeSet = []

			for i in range(len(app.optParams)):
				#find opt params for CBOE exchange
				if app.optParams[i][1] == 'CBOE':
					expSet = list(app.optParams[i][5])
					strikeSet = list(app.optParams[i][6])

					#append all expirations to a list
					for j in range(len(expSet)):
						#convert exp to date object and calculate days till expiration (DTE)
						expDate = datetime.datetime.strptime(expSet[j], "%Y%m%d")
						diff = abs((expDate - today).days)
						#append exp date, trading class & DTE
						self.exps.append([expSet[j], app.optParams[i][3], diff])

					#append all strikes to a list
					for k in range(len(strikeSet)):
						self.strikes.append([strikeSet[k], app.optParams[i][3]])
			#sort expiratoins in ascending order & strikes in descending order
			self.exps.sort()
			self.strikes.sort(reverse=True)
		except:
			print('Security Definiton Options Parameters Request Failed.')

		#find an expiration date to trade > 1 DTE, < 5 DTE
		try:
			#get contract expiration date
			for i in range(len(self.exps)):
				if self.exps[i][2] >= 1 and self.exps[i][2] <= 5:
					daysTillExp = (datetime.datetime.strptime(self.exps[i][0], "%Y%m%d") - today).days
					if ((self.optC.lastTradeDateOrContractMonth == None) or (self.exps[i][0] < self.optC.lastTradeDateOrContractMonth)) and (daysTillExp > 0):
						self.optC.lastTradeDateOrContractMonth = self.exps[i][0]
						self.optC.tradingClass = self.exps[i][1]
						self.DTE = (datetime.datetime.strptime(self.optC.lastTradeDateOrContractMonth, "%Y%m%d") - today).days
						self.conEXpDate = self.optC.lastTradeDateOrContractMonth
						self.tradingClass = self.optC.tradingClass
			#
			# filter strike list for the first nStrikes that are <= price target AND == expiration trading class
			strikeFilter = [list(filter(lambda n: (n[0]<= self.priceTarget) and (n[1] == self.optC.tradingClass), self.strikes))[i] for i in list(range(self.nStrikes))]
			# print(strikeFilter)
		except:
			print('Strike Filter exception')

		try:
			#iterate through strikes to request contract details & market data to get options greeks and contract IDs for order
			app.deets=[]
			reqList=[]
			for i in range(len(strikeFilter)):
				self.optC.strike = strikeFilter[i][0]

				#request market data
				try:
					spxID = getReqID()
					getMarketData(spxID, self.optC)
					app.reqContractDetails(spxID, self.optC)
					self.optGreeks.append([spxID, self.optC.strike])
				except:
					print(f'{self.optC.symbol} Market Data Request failed')
			time.sleep(4)
			# contractDetailsDF = pd.DataFrame(app.deets, columns=['ReqID','ConID','Symbol','LastTradeDate','Strike','Right','UnderlyingContractID'])
			# print(f'Contract Detail request for {self.optC.symbol} \n', contractDetailsDF)
		except:
			print('Strike contract ID request failed')

		self.getOptGreeks()

	def getOptGreeks(self):
		print('getOptGreeks')
		#get option greeks for each contract
		try:
			#get contract IDs from contract details
			for x in range(len(app.deets)):
				for y in range(len(self.optGreeks)):
					if (app.deets[x][0] == self.optGreeks[y][0]):
						self.optGreeks[y].append(app.deets[x][1])

			#get price data for each strike
			for i in range(len(self.optGreeks)):
				id = self.optGreeks[i][0]
				data = getOptionsGreeks(id)
				self.optGreeks[i] = self.optGreeks[i]+data[0][1:14]

			# print('\nOption Greeks: ',self.optGreeks)
		except:
			print('Unable to get optiions greeks!')
		# try:
		for i in range(len(self.optGreeks)):
			stopMarketData(self.optGreeks[i][0])

	def getGreeks(self):
		self.getConID()
		time.sleep(2)
		self.getOptionsChain()
		time.sleep(2)
		# pprint.pprint(self.__dict__)
		self.getOptGreeks()

#define run loop function
def run_loop():
	app.run()

#create new app API object and connect to API
app = IBapi()
app.connect(appConfig.TWS_IP, appConfig.TWS_PORT, appConfig.API_ID)

#Start the socket in a thread
try:
	api_thread = threading.Thread(target=run_loop, daemon=True)
	api_thread.start()
	time.sleep(1) #Sleep interval to allow time for connection to server
except:
	logging.error('Unable to start API thread!')

#Get unique request ID
def getReqID():
	reqUid = ReqUid().id
	return reqUid

#Check if current time is within regular trading hours
def tradingHours():
	#set trading hours in local time
	start = time.strptime("06:30:00", "%H:%M:%S")
	end = time.strptime("13:15:00", "%H:%M:%S")

	#get TWS time
	app.reqCurrentTime()
	time.sleep(1)
	twsTime = app.twsTime

	try:
		timeCheck = datetime.datetime.fromtimestamp(twsTime, tz=None).strftime("%a %d-%b-%Y %H:%M:%S")
		print('>>> Current TWS time: ', timeCheck)
		timeCheck = time.strptime(timeCheck, "%a %d-%b-%Y %H:%M:%S")
	except:
		print('Time Check Failed')

	#return true if current time is within range [start,end]
	if start <= end:
		return start <= timeCheck <= end
	else:
		return start <= timeCheck or currentTime <= end

#calculate available margin for trading
def tradeSize():
	lowMarginFlag = False
	availableMargin = float(app.accountData.get("ExcessLiquidity"))
	tradeMargin = round((availableMargin/4)/500)*500
	if availableMargin < 1000:
		lowMarginFlag = True

	return (tradeMargin, lowMarginFlag)

#start streaming market data request
def getMarketData(reqID, contract):
	# print(f'{type(self).__name__}.start: {contract.symbol}')
	app.reqMktData(reqID, contract, "", False, False, [])
	activeReqs.append(reqID)
	print(f'New Market Data Request: {reqID}, {contract.symbol}. # Active Requests: {len(activeReqs)}')

#stop streaming market data request
def stopMarketData(reqID):
	app.cancelMktData(reqID)
	activeReqs.remove(reqID)

	for i in range(len(app.marketData)):
		if (app.marketData[i][0] == reqID):
			app.marketData.pop(i)
			break
	print(f'Cancel Market Data Request: {reqID}. # Active Requests: {len(activeReqs)}')
#cancel all streaming market data

def stopAllMarketData():
	try:
		while len(activeReqs) > 0:
			reqID = activeReqs[0]
			app.cancelMktData(reqID)
			activeReqs.remove(reqID)
			print(f'Cancel Market Data Request: {reqID}. # Active Requests: {len(activeReqs)}')
			# time.sleep(0.2)
	except:
		print('Unable to cancel all Market Data Requests')

#check if portfolio has open SPX positions or open orders
def getOpenPositions():
	#check portfolio for open SPX position
	time.sleep(1) #wait to ensure we've received account details
	portfolioDF = pd.DataFrame(app.portfolio, columns=['Symbol', 'Security', 'Strike', 'Exp Date', 'Right',
	'position', 'marketPrice', 'marketValue', 'averageCost', 'unrealizedPNL', 'realizedPNL', 'accountName'])
	print('\nPortfolio: \n',portfolioDF)
	# portfolioDf.to_csv('portolio.csv')
	return(portfolioDF)

def checkOpenPositions(DF, symbol):
	flag = False
	openPosTest = DF[DF[DF['Symbol'].str.match(symbol)]['position'] != 0]
	if (openPosTest.empty == False):
		flag = True
	return(flag)

def getOpenOrders():
	# print('Request all open orders')
	app.openOrders = []
	app.reqAllOpenOrders()
	time.sleep(1)
	openOrdersDF = pd.DataFrame(app.openOrders, columns=["PermId", "ClientId", "OrderId",
	"Account", "Symbol", "SecType", "Exchange", "Action", "OrderType", "TotalQty", "CashQty", "LmtPrice", "AuxPrice", "Status"])
	print('\nOpen Orders: \n', openOrdersDF)
	return(openOrdersDF)

def checkOpenOrders(DF, symbol):
	flag = False
	openOrderTest = DF[DF['Symbol'].str.match(symbol)]
	if (openOrderTest.empty == False):
		flag = True
	return(flag)

#get VIX data
def getVixPrice():
	#get market data for VIX
	c = Contract()
	c.symbol = 'VIX'
	c.secType = 'IND'
	c.exchange = 'CBOE'
	c.currency = 'USD'
	id = getReqID()

	getMarketData(id, c)
	time.sleep(1)

	return(id)

def checkVixPrice(id):
	flag = False

	#check trading hours to use last or close price
	if tradingHours():
		tickPrice = TickTypeEnum.LAST + 1
	else:
		tickPrice = TickTypeEnum.CLOSE + 1

	for i in range(len(app.marketData)):
		if (app.marketData[i][0] == id):
			price = app.marketData[i][tickPrice]

	#VIX trading threshold is $30
	#if current price is at or above threshold then set VIX flag to True
	if price >= 30:
		flag = True

	return(flag)

def getOptionsGreeks(reqID):
	output = []
	for i in range(len(app.marketData)):
		id = app.marketData[i][0]

		if id == reqID:
			bidSize = app.marketData[i][1]
			bidPrice = app.marketData[i][2]
			askPrice = app.marketData[i][3]
			askSize = app.marketData[i][4]
			lastPrice = app.marketData[i][5]
			lastSize = app.marketData[i][6]
			modelOptionComp = app.marketData[i][14]

			#get options greeks for each strike
			if (modelOptionComp is None):
				greeks = [None] * 7
			else:
				iv = modelOptionComp[0]
				delta = modelOptionComp[1]
				pvDiv = modelOptionComp[2]
				gamma = modelOptionComp[3]
				vega = modelOptionComp[4]
				theta = modelOptionComp[5]
				undPrice = modelOptionComp[6]
				greeks = [undPrice, iv, delta, gamma, vega, theta, pvDiv]

			data = [id, bidPrice, bidSize, askPrice, askSize, lastPrice, lastSize] + greeks
			output.append(data)
	return(output)

def getComboStrikes(optGreeks,tradeMargin):
	#function to find the short & long strike prices for put spread combo based on options delta and available trade margin
	#find short strike
	shortStrike = 0
	shortConID = None
	shortDelta = None
	longStrike = 0
	longConID = None
	longDelta = None

	try:
		for i in range(len(optGreeks)):
			# print(optGreeks[i])
			d = optGreeks[i][11]
			# print('Target Delta: ', targetDelta)
			# print('Delta[i]: ', d)
			if (d is not None) and (abs(targetDelta - d) <= precision):
				# print('delta: ',d)
				if (optGreeks[i][1] > shortStrike):
					shortStrike = optGreeks[i][1]
					shortConID = optGreeks[i][2]
					shortDelta = optGreeks[i][11]
					print(shortStrike, shortConID, shortDelta)
	except:
		print('Unable to get short strike!')

	#find long strike
	try:
		strikeTarget = shortStrike - (tradeMargin/100)
		lastStrike = shortStrike
		for i in range(len(optGreeks)):
			# print(optGreeks[i])
			if (lastStrike is not None) and ((optGreeks[i][1] >= strikeTarget) and (optGreeks[i][1] < lastStrike)):
				longStrike = optGreeks[i][1]
				lastStrike = longStrike
				longConID = optGreeks[i][2]
				longDelta = optGreeks[i][11]
	except:
		print('Unable to get long strike!')

	print('\nShort Strike: ', shortStrike)
	print('Short Delta: ', shortDelta)
	print('Short Contract ID:', shortConID)
	print('Long Strike: ', longStrike)
	print('Long Delta: ', longDelta)
	print('Long Contract ID:', longConID)
	# stopAllMarketData()
	# time.sleep(5)
	return(shortConID,longConID)



def bracketOrder(action:str, quantity:float, limitPrice:float, takeProfitLimitPrice:float, stopLimitPrice:float, stopLossPrice:float):
	#get order IDs
	parentOrderId = app.nextOrderId()
	takeProfitOrderId = app.nextOrderId()
	stopLimitOrderId = app.nextOrderId()

	#parent order
	parent = Order()
	parent.orderId = parentOrderId
	parent.action = action
	parent.orderType = 'LMT'
	parent.totalQuantity = quantity
	parent.lmtPrice = limitPrice
	parent.tif = 'GTC'
	parent.eTradeOnly = False
	parent.firmQuoteOnly = False
	parent.transmit = False
	# pprint.pprint(parent.__dict__)
	print('Parent Order OK')

	#profit taker
	takeProfit = Order()
	takeProfit.orderId = takeProfitOrderId
	takeProfit.action = 'SELL' if action == 'BUY' else 'BUY'
	takeProfit.orderType = 'LMT'
	takeProfit.totalQuantity = quantity
	takeProfit.lmtPrice = takeProfitLimitPrice
	takeProfit.parentId = parentOrderId
	takeProfit.tif = 'GTC'
	takeProfit.eTradeOnly = False
	takeProfit.firmQuoteOnly = False
	takeProfit.transmit = False
	# pprint.pprint(takeProfit.__dict__)
	print('Take Profit Order OK')

	#stop limit
	stopLimit = Order()
	stopLimit.orderId = stopLimitOrderId
	stopLimit.action = 'SELL' if action == 'BUY' else 'BUY'
	stopLimit.orderType = 'STP LMT'
	stopLimit.totalQuantity = quantity
	stopLimit.lmtPrice = stopLimitPrice
	stopLimit.auxPrice = stopLossPrice
	stopLimit.parentId = parentOrderId
	stopLimit.tif = 'GTC'
	stopLimit.eTradeOnly = False
	stopLimit.firmQuoteOnly = False
	stopLimit.transmit = True
	# pprint.pprint(stopLimit.__dict__)
	print('Stop Limit Order OK')

	bracket = [parent, takeProfit, stopLimit]
	# pprint.pprint(bracket.__dict__)
	return(bracket)

def getComboOrder(orderPrice):

	takeProfitLimitPrice = round((orderPrice * 0.3)/5, 2)*5
	stopLimitPrice = round((orderPrice * 3)/5, 2)*5
	stopLossPrice = round((stopLimitPrice - 0.5)/5, 2)*5

	# oid = app.nextOrderId()

	print('Order Limit Price: ', orderPrice)
	print('ProfitTaker Limit Price: ', takeProfitLimitPrice)
	print('Stop Price: ', stopLossPrice)
	print('Stop Limit Price: ', stopLimitPrice)

	#get combo order with bracket profit-taker + stop-limit
	try:
		comboOrder = bracketOrder('BUY', 1, orderPrice, takeProfitLimitPrice, stopLimitPrice, stopLossPrice)
		print('\nCombo Order: ',comboOrder)
	except:
		print('Unable to get combo order!')

	return(comboOrder)

def getOrderPrice(comboID, orderMod, lastParentId, lastOrderPrice):
	print('>>> Getting order price <<<')
	comboGreeks = getOptionsGreeks(comboID)
	comboGreeksDF = pd.DataFrame(comboGreeks, columns=['ID','Bid','BidSize','Ask','AskSize','Last','LastSize','Underlying','IV','Delta','Gamma','Vega','Theta','PVDiv'])
	print('\n',comboGreeksDF)

	bid = comboGreeks[0][1]
	ask = comboGreeks[0][3]

	#set order limit price to bid
	if orderMod == False:
		#submit initial order limit price @Bid; get new order ID
		orderPrice = round((bid/5), 2)*5
	else:
		orderPrice = round((((bid+ask)/2)/5), 2)*5

		if orderPrice == lastOrderPrice:
			print('New price is the same as old price!')
			time.sleep(10)
			return(getOrderPrice(comboID, orderMod, lastParentId, lastOrderPrice))

		#cancel existing orders
		try:
			app.cancelOrder(lastParentId)
			# app.reqGlobalCancel()
			time.sleep(3)
		except:
			print('Unable to cancel orders!')

		#submit order mod limit price  @Bid/Ask midpoint; reuse order ID
		# print('Modifying Order; Attempt: ', modAttempt)
		print('Modifying Order')
		# modAttempt += 1

	print('Order Price: ', orderPrice)
	return(orderPrice)

def comboLegLoop(cSPX, priceTarget, tradeMargin):
	# [optGreeks, conExpDate, DTE, tradingClass] = getOptChains(cSPX, priceTarget)
	# print('comboLegLoop start', cSPX, priceTarget, tradeMargin)
	og = OptionGreeks(cSPX, priceTarget)
	og.getConID()

	#try to get combo strikes
	shortConID = None
	longConID = None

	while (shortConID is None) or (longConID is None):
		optGreeks = og.optGreeks
		conExpDate = og.conEXpDate
		DTE = og.DTE
		tradingClass = og.tradingClass

		# streamingFlag = True

		print('\nContract Expiration Date: ',conExpDate)
		print('\nDTE: ',DTE)
		print(f'\nAccount Update Time: {app.accountData.get("Time")}')

		optGreeksDF = pd.DataFrame(optGreeks, columns=['ID','Strike','ContractID','Bid','BidSize','Ask','AskSize','Last','LastSize','Underlying','IV','Delta','Gamma','Vega','Theta','PVDiv'])
		print('\n',optGreeksDF)

		[shortConID, longConID] = getComboStrikes(optGreeks,tradeMargin)
		print('Short Leg Contract ID:',shortConID)
		print('Long Leg Contract ID:',longConID)

		if (shortConID is None) or (longConID is None):
			print('\n>>>Option Greeks Not Available<<<\n')
			time.sleep(2)
			og.getConID()

	return(shortConID, longConID, tradingClass, conExpDate)
"""

main trading strategy logic

"""
def optionsStrategy():
	#subscribe to account & portfolio updates
	try:
		app.reqAccountUpdates(True, appConfig.ACCOUNT_NUMBER)
		time.sleep(requestDelay)
		# app.reqGlobalCancel()

		# app.reqIds(-1)
	except:
		logging.error('Request Account Update Failed')
		print('\nRequest Account Update Failed')

	#start VIX market data
	vixId = getVixPrice()
	loopFlag = True

	#run continuously in a loop
	while loopFlag == True:
		#define SPX contract object
		cSPX = Contract()
		cSPX.symbol = 'SPX'
		cSPX.secType = 'IND'
		cSPX.exchange = 'CBOE'
		cSPX.currency = 'USD'

		"""
		Need to ensure that the following conditions are met before proceeding with trade strategy:
		1) Market Open
		2) No open SPX positions in portfolio
		3) No pending/submitted SPX orders awaiting execution
		4) VIX is below $30
		"""

		#set flags
		marketOpenFlag = False
		positionFlag = True
		openOrderFlag = True
		vixFlag = True
		tradeConditionsMet = False

		#run loop to check if open positions/orders exist or if VIX is above $30 threshold
		while (tradeConditionsMet == False):
			#show account data
			tradeMargin = tradeSize()[0]
			print(f'\nNet Liquidation: ${app.accountData.get("NetLiquidation")}')
			print(f'Initial Margin: ${app.accountData.get("InitMarginReq")}')
			print(f'Maintenance Margin: ${app.accountData.get("MaintMarginReq")}')
			print(f'Total Cash: ${app.accountData.get("TotalCashValue")}')
			print(f'Unrealized PNL: ${app.accountData.get("UnrealizedPnL")}')
			print(f'Realized PNL: ${app.accountData.get("RealizedPnL")}')
			print(f'Trade Margin: $',tradeMargin)

			#check if market is open
			if checkTradingHours == True:
				marketOpenFlag = tradingHours()
			else:
				marketOpenFlag = True


			if (marketOpenFlag == False):
				print(f'>>> Outside of Trading Hours! <<<')
			else:
				#check for open SPX positions
				portfolioData = getOpenPositions()
				positionFlag = checkOpenPositions(portfolioData, cSPX.symbol)

				#check for open SPX orders
				openOrderData = getOpenOrders()
				openOrderFlag = checkOpenOrders(openOrderData, cSPX.symbol)

				if (positionFlag == True) or (openOrderFlag == True):
					print(f'\n>>> Open SPX Position or Order! - Waiting {loopDelay} seconds <<<')
				else:
					print(f'\n>>> No open SPX positions/orders; processing...')

				vixFlag = checkVixPrice(vixId)
				if (vixFlag == True):
					print(f'>>> Current VIX price above $30 threshold! <<< ')

			#check if trade conditions are met
			if (marketOpenFlag == True) and (positionFlag == False) and (openOrderFlag == False) and (vixFlag == False):
				tradeConditionsMet = True
			else:
				time.sleep(loopDelay)

		#get current SPX price - probably not needed

		try:
			spxID = getReqID()
			print('Get Market Data')
			getMarketData(spxID, cSPX)
			time.sleep(1)

			#check trading hours to use last or close price
			if tradingHours():
				tickPrice = TickTypeEnum.LAST + 1
			else:
				tickPrice = TickTypeEnum.CLOSE + 1

			print('Find last price')
			for i in range(len(app.marketData)):
				if (app.marketData[i][0] == spxID):
					spxCurrentPrice = app.marketData[i][tickPrice]

			print(f'SPX price: {spxCurrentPrice}')
			stopMarketData(spxID)
			# print('Calc price target')
			priceTarget = round((spxCurrentPrice * targetFactor), 0)
			print(f'\nCurrent SPX Price: {spxCurrentPrice} \nPrice Target: {priceTarget}\n')
		except:
			print('\nUnable to get SPX price target')

		#get contract IDs for combo legs, loop until valid data is returned
		[shortConID, longConID, tradingClass, conExpDate] = comboLegLoop(cSPX, priceTarget, tradeMargin)
		print('>>> Building Options Spread Contract...')

		#options spread contract
		c = Contract()
		c.symbol = 'SPX'
		c.secType = 'BAG'
		c.currency = 'USD'
		c.exchange = 'CBOE'
		c.lastTradeDateOrContractMonth = conExpDate
		c.tradingClass = tradingClass
		# print(c.tradingClass)

		leg1 = ComboLeg()
		leg1.conId = shortConID
		leg1.ratio = 1
		leg1.action = 'SELL'
		leg1.exchage = 'CBOE'

		leg2 = ComboLeg()
		leg2.conId = longConID
		leg2.ratio = 1
		leg2.action = 'BUY'
		leg2.exchage = 'CBOE'

		c.comboLegs = []
		c.comboLegs.append(leg1)
		c.comboLegs.append(leg2)

		# pprint.pprint(c.__dict__)

		#get spread contract market data
		comboID = getReqID()
		getMarketData(comboID, c)
		time.sleep(requestDelay)

		"""
		Need to add loop for order modification
		"""
		orderFilled = False
		orderMod = False
		lastParentId = 0
		lastOrderPrice = 0
		modAttempt = 1

		while (orderFilled == False):

			orderPrice = getOrderPrice(comboID, orderMod, lastParentId, lastOrderPrice)
			comboOrder = getComboOrder(orderPrice)

			#send order to TWS
			try:
				print('Placing Order')
				for o in comboOrder:
					# pprint.pprint(o.__dict__)
					app.placeOrder(o.orderId, c, o)
					# app.nextOrderId()
				lastParentId = comboOrder[0].orderId
				lastOrderPrice = comboOrder[0].lmtPrice
			except:
				print('Unable to place order')

			time.sleep(1)
			getOpenOrders()

			time.sleep(5)
			#check if order is filled
			if len(app.executions) == 0:
				orderMod = True
			else:
				orderFilled = True
				orderMOd = False
				for i in range(len(app.executions)):
					print(app.executions[i][4])
					try:
						execution = app.executions[i][4]
						filledId = execution.orderId
						print(filledId)
						if filledID == oid:
							orderFilled = True
						else:
							orderMod = True
					except:
						print('Execution exception!')


			print(f'\nOrder Filled: {orderFilled}\nOrder Mod: {orderMod}')
			"""
			Todo:
			test order execution & modification logic
			build trade log
			setup daily email summary
			"""

		#cancel market data
		stopMarketData(comboID)
		time.sleep(loopDelay)

#execute optionsStrategy
try:
	optionsStrategy()
except:
	# app.reqGlobalCancel()
	app.cancelOrder(lastParentId)
	stopAllMarketData()

app.disconnect()
