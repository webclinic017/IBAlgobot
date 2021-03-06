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
from ibapi import order_condition
from ibapi.order_condition import *
from ibapi.contract import *
from ibapi.order import *
from ibapi.order_state import * # @UnusedWildImport
from ibapi.execution import Execution
from ibapi.execution import ExecutionFilter
from ibapi.commission_report import CommissionReport
from ibapi.ticktype import *
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
import logging
import math



#Get current timestamp
def getTimeNow():
	timeNow = datetime.datetime.now().strftime("%d%b%y_%H%M%S_%f")
	return timeNow
#log config
class CustomFormatter(logging.Formatter):

    grey = "\x1b[38;21m"
    green = "\x1b[32;21m"
    yellow = "\x1b[33;21m"
    red = "\x1b[31;21m"
    bold_red = "\x1b[41;41m"
    # bold_red = "\x1b[31;1m"
    reset = "\x1b[0m"
    format = "%(asctime)s.%(name)s.%(lineno)d.%(levelname)s:  %(message)s"

    FORMATS = {
        logging.DEBUG: green + format + reset,
        logging.INFO: grey + format + reset,
        logging.WARNING: yellow + format + reset,
        logging.ERROR: red + format + reset,
        logging.CRITICAL: bold_red + format + reset
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt)
        return formatter.format(record)

#create logger
moduleName = 'IBTradingBot'
log = logging.getLogger(moduleName)
log.setLevel(logging.DEBUG)
#create file handler
fh = logging.FileHandler('app.log')
fh.setLevel(logging.DEBUG)
#create console handler
ch = logging.StreamHandler()
ch.setLevel(logging.INFO)
#create formatter & add it to handlers
formatter = logging.Formatter('%(asctime)s.%(name)s.%(levelname)s: %(message)s','%Y%m%d_%H:%M:%S')
fh.setFormatter(formatter)
ch.setFormatter(CustomFormatter())
# ch.setFormatter(formatter)
#add handlers to logger
log.addHandler(fh)
log.addHandler(ch)

# logging.basicConfig(filename=f'trading_bot.log', level=logging.INFO)
# log.info("now is %s", datetime.datetime.now())

#define connection variables
TWS_IP = '127.0.0.1'
TWS_PORT = 7497
API_ID = 1
ACCOUNT_NUMBER = '' #update account number 

# appConfig = AppConfig()

#define other program variables
checkTradingHours = True
reqUID = 1000
vixFlag = 0
optMaxDTE = 3
optMinDTE = 1
activeReqs = []
activeOrders = []
targetFactor = 1
nStrikes = 45
# targetDelta = -0.08
profitTarget = .55
stopTarget = .55
maxTradeMargin = 0.75
spreadLimit = 20000 #upper limit of spread margin
precision = 0.05
backtestFlag = False
requestDelay = 1
loopDelay = 10
lastParentId = 0

...
log.info('##### %s #####', getTimeNow())

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
		self.conExpDate = None
		self.tradingClass = None
		self.priceTarget = priceTarget
		# self.log = logging.getLogger('IBTradingBot.twsapi.OptionGreeks')
		# self.tradeMargin = tradeSize()[0]

	def getConID(self):
		#request contract details to get contract ID
		# print(f'Request {self.c.symbol} contract details')
		log.debug(f'Request %s contract details', self.c.symbol)
		try:
			app.deets = []
			app.reqContractDetails(getReqID(), self.c)
			time.sleep(1)
			contractDetailsDF = pd.DataFrame(app.deets, columns=['ReqID','ConID','Symbol','LastTradeDate','Strike','Right','UnderlyingContractID'])
			log.debug('Contract Detail request for %s', self.c.symbol)
			log.debug('contractDetailsDF: \n %s', contractDetailsDF)
			# print(f'Contract Detail request for {self.c.symbol} \n', contractDetailsDF)
			self.underCID = app.deets[0][6]
			conID = app.deets[0][1]
			if (self.c.secType == 'STK') or (self.c.secType == 'IND'):
				self.underCID = conID
		except:
			log.error('Contract Details Request Failed')

		self.getOptionsChain()

	def getOptionsChain(self):
		#Reqeust options chain
		log.info('Request %s options chain',self.optC.symbol)
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
			log.error('Security Definiton Options Parameters Request Failed.')

		#find an expiration date to trade > 1 DTE, < 5 DTE
		try:
			#get contract expiration date
			for i in range(len(self.exps)):
				if self.exps[i][2] >= optMinDTE and self.exps[i][2] <= optMaxDTE:
					daysTillExp = (datetime.datetime.strptime(self.exps[i][0], "%Y%m%d") - today).days
					if ((self.optC.lastTradeDateOrContractMonth == None) or (self.exps[i][0] < self.optC.lastTradeDateOrContractMonth)) and (daysTillExp > 0):
						self.optC.lastTradeDateOrContractMonth = self.exps[i][0]
						self.optC.tradingClass = self.exps[i][1]
						self.DTE = (datetime.datetime.strptime(self.optC.lastTradeDateOrContractMonth, "%Y%m%d") - today).days
						self.conExpDate = self.optC.lastTradeDateOrContractMonth
						self.tradingClass = self.optC.tradingClass
			#
			# filter strike list for the first nStrikes that are <= price target AND == expiration trading class
			strikeFilter = [list(filter(lambda n: (n[0]<= self.priceTarget) and (n[1] == self.optC.tradingClass), self.strikes))[i] for i in list(range(self.nStrikes))]
			# print(strikeFilter)
		except:
			log.error('Strike Filter exception')

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
					log.error('%s Market Data Request failed',self.optC.symbol)
			time.sleep(4)
			# contractDetailsDF = pd.DataFrame(app.deets, columns=['ReqID','ConID','Symbol','LastTradeDate','Strike','Right','UnderlyingContractID'])
			# print(f'Contract Detail request for {self.optC.symbol} \n', contractDetailsDF)
		except:
			log.error('Strike contract ID request failed')

		self.getOptGreeks()

	def getOptGreeks(self):
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
			log.error('Unable to get optiions greeks!')
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

def apiConnect():
	app.connect(TWS_IP, TWS_PORT, API_ID)
	log.info('>>> API Connecting <<<')

#create new app API object and connect to API
app = IBapi()
apiConnect()

#create funciton to check if connected to TWS
def connectionMonitor():
	log = logging.getLogger(moduleName+'.connectionMonitor')
	wait = 2
	while True:
		if app.connected == False:
			log.critical('Connection to TWS Broken!')
			apiConnect()
			log.warning('Reconnecting...')
			time.sleep(wait)
			wait = wait * 1.5



#Start the socket in a thread
try:
	api_thread = threading.Thread(target=run_loop, daemon=True)
	api_thread.start()
	time.sleep(1) #Sleep interval to allow time for connection to server
except:
	log.error('Unable to start API thread!')

try:
	connMon_thread = threading.Thread(target=connectionMonitor, daemon=True)
	connMon_thread.start()
except:
	log.error('Unable to start connection monitor thread!')
#Get unique request ID
def getReqID():
	reqUid = ReqUid().id
	return reqUid

#Check if current time is within regular trading hours
def tradingHours():
	log = logging.getLogger(moduleName+'.tradingHours')
	log.debug('checking trading hours')
	#set trading hours in local time
	start = time.strptime("06:30:00", "%H:%M:%S")
	end = time.strptime("13:15:00", "%H:%M:%S")
	log.debug('start: %s', time.strftime("%H:%M:%S",start))
	log.debug('end: %s', time.strftime("%H:%M:%S",end))

	#get TWS time
	try:
		app.reqCurrentTime()
		time.sleep(requestDelay)
		twsTime = app.twsTime
		log.debug('twsTime: %s', twsTime)
	except:
		log.error('TWS current time request failed')

	try:
		timeCheck = datetime.datetime.fromtimestamp(twsTime, tz=None).strftime("%H %M %S")
		timeCheck = time.strptime(timeCheck, "%H %M %S")
		log.debug('timeCheck: %s', time.strftime("%H:%M:%S",timeCheck))
	except:
		log.error('Time Check Failed')

	#return true if current time is within range [start,end]
	if start <= end:
		return start <= timeCheck <= end
	else:
		return start <= timeCheck or currentTime <= end

#calculate available margin for trading
# def tradeSize():
# 	lowMarginFlag = False
# 	availableMargin = float(app.accountData.get("ExcessLiquidity"))
# 	tradeMargin = round((availableMargin/4)/500)*500
# 	if availableMargin < 1000:
# 		lowMarginFlag = True
#
# 	return (tradeMargin, lowMarginFlag)
def TimeCondition(time:str, isMore:bool, isConjunction:bool):

	#! [time_condition]
	timeCondition = order_condition.Create(OrderCondition.Time)
	#Before or after...
	timeCondition.isMore = isMore
	#this time..
	timeCondition.time = time
	#AND | OR next condition (will be ignored if no more conditions are added)
	timeCondition.isConjunctionConnection = isConjunction
	#! [time_condition]
	return timeCondition

def tradeSize():
	marginAvailable = float(app.accountData.get("ExcessLiquidity"))
	if marginAvailable > spreadLimit:
		qty = math.ceil(marginAvailable/spreadLimit)
		margin = round(marginAvailable/(qty*500),0)*500
	else:
		qty = 1
		margin = marginAvailable
	return(margin,qty)

def setShortDelta(VIX):
	#set short delta based on VIX
	if VIX >= 50:
		sd = 0
	elif (VIX < 50) and (VIX >= 45):
		sd = -0.06
	elif (VIX < 45) and (VIX >= 35):
		sd = -0.08
	elif (VIX < 35) and (VIX >= 30):
		sd = -0.10
	elif (VIX < 30) and (VIX >= 25):
		sd = -0.15
	elif (VIX < 25) and (VIX >= 20):
		sd = -0.20
	elif (VIX < 20) and (VIX >= 15):
		sd = -0.30
	elif (VIX < 15) and (VIX >= 10):
		sd = -0.40
	elif (VIX < 10) and (VIX >= 5):
		sd = -0.50

	return(sd)



#start streaming market data request
def getMarketData(reqID, contract):
	log = logging.getLogger(moduleName+'.getMarketData')
	app.reqMktData(reqID, contract, "", False, False, [])
	activeReqs.append(reqID)
	log.info('New Market Data Request: %s, %s  # Active Requests: %s ', reqID, contract.symbol, len(activeReqs))

#stop streaming market data request
def stopMarketData(reqID):
	log = logging.getLogger(moduleName+'.stopMarketData')
	app.cancelMktData(reqID)
	activeReqs.remove(reqID)

	for i in range(len(app.marketData)):
		if (app.marketData[i][0] == reqID):
			app.marketData.pop(i)
			break
	log.info('Cancel Market Data Request: %s # Active Requests: %s', reqID, len(activeReqs))
#cancel all streaming market data

def stopAllMarketData():
	log = logging.getLogger(moduleName+'.stopAllMarketData')
	try:
		while len(activeReqs) > 0:
			reqID = activeReqs[0]
			app.cancelMktData(reqID)
			activeReqs.remove(reqID)
			log.info('Cancel Market Data Request: %s # Active Requests: %s', reqID, len(activeReqs))
			# time.sleep(0.2)
	except:
		log.error('Unable to cancel all Market Data Requests')

#check if portfolio has open SPX positions or open orders
def getOpenPositions():
	log = logging.getLogger(moduleName+'.getOpenPositions')
	#check portfolio for open SPX position
	time.sleep(1) #wait to ensure we've received account details
	portfolioDF = pd.DataFrame(app.portfolio, columns=['Symbol', 'Security', 'Strike', 'Exp Date', 'Right',
	'position', 'marketPrice', 'marketValue', 'averageCost', 'unrealizedPNL', 'realizedPNL', 'accountName'])
	log.info('Portfolio: \n\n %s \n',portfolioDF)
	return(portfolioDF)

def checkOpenPositions(DF, symbol):
	flag = False
	openPosTest = DF[DF[DF['Symbol'].str.match(symbol)]['position'] != 0]
	if (openPosTest.empty == False):
		flag = True
	return(flag)

def getOpenOrders():
	log = logging.getLogger(moduleName+'.getOpenOrders')
	# print('Request all open orders')
	app.openOrders = []
	app.reqAllOpenOrders()
	time.sleep(1)
	openOrdersDF = pd.DataFrame(app.openOrders, columns=["PermId", "ClientId", "OrderRef", "ParentId", "OrderId",
	"Account", "Symbol", "SecType", "Exchange", "Action", "OrderType", "TotalQty", "CashQty", "LmtPrice", "AuxPrice", "Status"])
	log.info('Open Orders: \n\n%s\n', openOrdersDF)
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
	log = logging.getLogger(moduleName+'.checkVixPrice')
	flag = False

	#check trading hours to use last or close price
	try:
		tradingHoursFlag = tradingHours()
		log.debug('tradingHours: %s', tradingHoursFlag)
		if tradingHoursFlag:
			tickPrice = TickTypeEnum.LAST + 1
		else:
			tickPrice = TickTypeEnum.CLOSE + 1
	except:
		log.error('Something failed')

	try:
		for i in range(len(app.marketData)):
			if (app.marketData[i][0] == id):
				price = app.marketData[i][tickPrice]
	except:
		log.error('Unable to get VIX market data')
	log.debug('VIX Price: %s',price)
	#VIX trading threshold is $30
	#if current price is at or above threshold then set VIX flag to True

	shortDelta = setShortDelta(price)

	if price >= 50:
		flag = True

	return(flag, shortDelta)

def getOptionsGreeks(reqID):
	log = logging.getLogger(moduleName+'.getOptionsGreeks')
	output = []
	dataFlag = False
	log.debug('ReqID: %s', reqID)
	for i in range(len(app.marketData)):
		id = app.marketData[i][0]

		if id == reqID:
			log.debug('Market Data: \n%s', app.marketData[i])
			dataFlag = True
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
	log.debug('Options Greeks Data:\n%s', output)
	if dataFlag == False:
		log.critical('No Options Greeks Data... check market data subscription!')
		time.sleep(3)
		return getOptionsGreeks(reqID)
	return(output)

def getComboStrikes(optGreeks,tradeMargin,targetDelta):
	log = logging.getLogger(moduleName+'.getComboStrikes')
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
					# log.debug('Short Strike: %s, ShortConID: %s, ShortDelta: %s',shortStrike, shortConID, shortDelta)
	except:
		log.error('Unable to get short strike!')

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
		log.error('Unable to get long strike!')

	log.info('Short Strike: %s', shortStrike)
	log.info('Short Delta: %s', shortDelta)
	log.info('Short Contract ID: %s', shortConID)
	log.info('Long Strike: %s', longStrike)
	log.info('Long Delta: %s', longDelta)
	log.info('Long Contract ID: %s', longConID)
	# stopAllMarketData()
	# time.sleep(5)
	return(shortConID,longConID)



def bracketOrder(action:str, quantity:float, limitPrice:float, takeProfitLimitPrice:float, stopLimitPrice:float, stopLossPrice:float, conExpDate):
	log = logging.getLogger(moduleName+'.bracketOrder')
	#get order IDs
	parentOrderId = app.nextOrderId()
	takeProfitOrderId = app.nextOrderId()
	stopLimitOrderId = app.nextOrderId()
	orderRef = datetime.datetime.now().strftime("%Y%m%d%H%M%S")

	log.debug('Exp Date: %s', conExpDate + " 23:59:59")
	timeCondition = TimeCondition(conExpDate + " 23:59:59", False, False)
	log.debug('Time Condition: %s', timeCondition.__dict__)

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
	parent.orderRef = orderRef
	# pprint.pprint(parent.__dict__)
	log.debug('Parent Order OK')

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
	takeProfit.orderRef = orderRef
	# takeProfit.conditions.append(TimeCondition(conExpDate + " 23:59:59", False, False))
	# pprint.pprint(takeProfit.__dict__)
	log.debug('Take Profit Order OK')

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
	stopLimit.orderRef = orderRef
	# stopLimit.conditions.append(TimeCondition(conExpDate + " 23:59:59", False, False))
	# pprint.pprint(stopLimit.__dict__)
	log.debug('Stop Limit Order OK')

	bracket = [parent, takeProfit, stopLimit]
	# pprint.pprint(bracket.__dict__)
	return(bracket)

def getComboOrder(orderPrice, tradeMargin, profitTarget, stopTarget, qty, conExpDate):
	log = logging.getLogger(moduleName+'.getComboOrder')

	# takeProfitLimitPrice = round((orderPrice * 0.3)/5, 2)*5
	takeProfitLimitPrice = round((orderPrice * (1 - profitTarget))/5, 2)*5
	# stopLimitPrice = round((orderPrice * 3)/5, 2)*5
	stopLimitPrice = round((orderPrice * (stopTarget * ((tradeMargin)/1000 )))/5, 2)*5
	stopLossPrice = round((stopLimitPrice + 0.5)/5, 2)*5

	log.info('Order Limit Price: %s', orderPrice)
	log.info('ProfitTaker Limit Price: %s', takeProfitLimitPrice)
	log.info('Stop Price: %s', stopLossPrice)
	log.info('Stop Limit Price: %s', stopLimitPrice)

	#get combo order with bracket profit-taker + stop-limit
	try:
		comboOrder = bracketOrder('BUY', qty, orderPrice, takeProfitLimitPrice, stopLimitPrice, stopLossPrice, conExpDate)
		log.info('Combo Order: \n%s\n',comboOrder)
	except:
		log.error('Unable to get combo order!')

	return(comboOrder)

def getOrderPrice(comboID, orderMod, lastParentId, lastOrderPrice):
	log = logging.getLogger(moduleName+'.getOrderPrice')
	log.info('>>> Getting order price <<<')
	comboGreeks = getOptionsGreeks(comboID)
	comboGreeksDF = pd.DataFrame(comboGreeks, columns=['ID','Bid','BidSize','Ask','AskSize','Last','LastSize','Underlying','IV','Delta','Gamma','Vega','Theta','PVDiv'])
	log.debug('comboGreeksDF: \n\n%s\n',comboGreeksDF)

	bid = comboGreeks[0][1]
	ask = comboGreeks[0][3]

	#set order limit price to bid
	if orderMod == False:
		#submit initial order limit price @Bid; get new order ID
		orderPrice = round((bid/5), 2)*5
	else:
		orderPrice = round((((bid+ask)/2)/5), 2)*5

		if orderPrice == lastOrderPrice:
			log.error('New price is the same as old price!')
			time.sleep(10)
			return(getOrderPrice(comboID, orderMod, lastParentId, lastOrderPrice))

		#cancel existing orders
		try:
			app.cancelOrder(lastParentId)
			# app.reqGlobalCancel()
			time.sleep(3)
		except:
			log.error('Unable to cancel orders!')

		#submit order mod limit price  @Bid/Ask midpoint; reuse order ID
		# print('Modifying Order; Attempt: ', modAttempt)
		log.info('Modifying Order')
		# modAttempt += 1

	log.info('Order Price: %s', orderPrice)
	return(orderPrice)

def comboLegLoop(cSPX, priceTarget, tradeMargin, targetDelta):
	log = logging.getLogger(moduleName+'.comboLegLoop')
	# [optGreeks, conExpDate, DTE, tradingClass] = getOptChains(cSPX, priceTarget)
	# print('comboLegLoop start', cSPX, priceTarget, tradeMargin)
	og = OptionGreeks(cSPX, priceTarget)
	og.getConID()

	#try to get combo strikes
	shortConID = None
	longConID = None

	while (shortConID is None) or (longConID is None):
		optGreeks = og.optGreeks
		conExpDate = og.conExpDate
		DTE = og.DTE
		tradingClass = og.tradingClass

		# streamingFlag = True

		log.info('Contract Expiration Date: %s',conExpDate)
		log.info('DTE: %s',DTE)
		log.info('Account Update Time: %s', app.accountData.get("Time"))

		optGreeksDF = pd.DataFrame(optGreeks, columns=['ID','Strike','ContractID','Bid','BidSize','Ask','AskSize','Last','LastSize','Underlying','IV','Delta','Gamma','Vega','Theta','PVDiv'])
		log.debug('optGreeksDF: \n%s\n',optGreeksDF)

		[shortConID, longConID] = getComboStrikes(optGreeks,tradeMargin,targetDelta)
		log.info('Short Leg Contract ID: %s',shortConID)
		log.info('Long Leg Contract ID: %s',longConID)

		if (shortConID is None) or (longConID is None):
			log.error('>>>Option Greeks Not Available<<<')
			time.sleep(2)
			og.getConID()

	return(shortConID, longConID, tradingClass, conExpDate)
"""

main trading strategy logic

"""
def optionsStrategy():
	log = logging.getLogger(moduleName+'.optionsStrategy')
	#subscribe to account & portfolio updates

	if app.connected == False:
		time.sleep(15)
		optionsStrategy()

	try:
		app.reqAccountUpdates(True, ACCOUNT_NUMBER)
		time.sleep(requestDelay)
		# app.reqGlobalCancel()

		# app.reqIds(-1)
	except:
		log.error('Request Account Update Failed')
		# print('Request Account Update Failed')

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
			#check if API is connected, if not reconnect
			# if app.connected == False:
			# 	apiConnect()
			# 	time.sleep(1)
			#show account data
			[tradeMargin, qty] = tradeSize()
			log.info('Net Liquidation: $%s',app.accountData.get("NetLiquidation"))
			log.info('Initial Margin: $%s',app.accountData.get("InitMarginReq"))
			log.info('Maintenance Margin: $%s',app.accountData.get("MaintMarginReq"))
			log.info('Total Cash: $%s',app.accountData.get("TotalCashValue"))
			log.info('Unrealized PNL: $%s',app.accountData.get("UnrealizedPnL"))
			log.info('Realized PNL: $%s',app.accountData.get("RealizedPnL"))
			log.info('Trade Margin: $%s',tradeMargin)

			#check if market is open
			if checkTradingHours == True:
				marketOpenFlag = tradingHours()
			else:
				marketOpenFlag = True


			if (marketOpenFlag == False):
				log.warning('>>> Outside of Trading Hours! <<<')
			# else:

			#check for open SPX positions
			portfolioData = getOpenPositions()
			positionFlag = checkOpenPositions(portfolioData, cSPX.symbol)

			#check for open SPX orders
			openOrderData = getOpenOrders()
			openOrderFlag = checkOpenOrders(openOrderData, cSPX.symbol)

			if (openOrderFlag == True):
				if (positionFlag == True):
					log.warning('>>> Open SPX Position or Order! <<<')
				elif (positionFlag == False):
					log.error('>>> Orphaned Orders! <<<')
					app.reqGlobalCancel()
			else:
				log.info('>>> No open SPX positions/orders <<<')

			[vixFlag, targetDelta] = checkVixPrice(vixId)
			if (vixFlag == True):
				log.warning('>>> Current VIX price above $30 threshold! <<< ')

			#check if trade conditions are met
			if (marketOpenFlag == True) and (positionFlag == False) and (openOrderFlag == False) and (vixFlag == False):
				tradeConditionsMet = True
				log.info('>>> Processing <<<')
			else:
				log.warning('>>> Trading Conditions Not Met - Waiting %s seconds <<<',loopDelay)
				time.sleep(loopDelay)

		#get current SPX price - probably not needed

		try:
			spxID = getReqID()
			log.info('Get Market Data')
			getMarketData(spxID, cSPX)
			time.sleep(1)

			#check trading hours to use last or close price
			if marketOpenFlag == True:
				tickPrice = TickTypeEnum.LAST + 1
			else:
				tickPrice = TickTypeEnum.CLOSE + 1

			log.info('Find last price')
			for i in range(len(app.marketData)):
				log.debug('market data: \n%s',app.marketData[i])
				if (app.marketData[i][0] == spxID):
					spxCurrentPrice = app.marketData[i][tickPrice]

			log.info(f'SPX price: %s',spxCurrentPrice)
			stopMarketData(spxID)
			# print('Calc price target')
			priceTarget = round((spxCurrentPrice * targetFactor), 0)
			log.info('Current SPX Price: %s Price Target: %s', spxCurrentPrice, priceTarget)
		except:
			log.critical('Failure')
			raise ValueError('Unable to get SPX price target')

		#get contract IDs for combo legs, loop until valid data is returned
		[shortConID, longConID, tradingClass, conExpDate] = comboLegLoop(cSPX, priceTarget, tradeMargin, targetDelta)
		log.info('>>> Building Options Spread Contract...')

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
			comboOrder = getComboOrder(orderPrice, tradeMargin, profitTarget, stopTarget, qty, conExpDate)
			oid = comboOrder[0].orderId

			#send order to TWS
			try:
				log.info('Placing Order')
				for o in comboOrder:
					# pprint.pprint(o.__dict__)
					app.placeOrder(o.orderId, c, o)
					# app.nextOrderId()
				lastParentId = comboOrder[0].orderId
				lastOrderPrice = comboOrder[0].lmtPrice
			except:
				log.error('Unable to place order')

			time.sleep(1)
			getOpenOrders()

			time.sleep(5)
			#check if order is filled
			if len(app.executions) == 0:
				orderMod = True
			else:
				# orderFilled = True
				orderMOd = False
				for i in range(len(app.executions)):
					# try:
					filledId = app.executions[i][4]
					execTime = app.executions[i][1]

					if filledId == oid:
						orderFilled = True
						log.info('Order %s filled at %s', filledId, execTime)
					else:
						orderMod = True
					# except:
					# 	log.error('Execution exception!')


			log.info('Order Filled: %s', orderFilled)
			log.info('Order Mod: %s', orderMod)
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
except KeyboardInterrupt:
	log.info('Shutting down...')
finally:
	# app.reqGlobalCancel()
	app.cancelOrder(lastParentId)
	stopAllMarketData()
	app.disconnect()
	logging.shutdown()
