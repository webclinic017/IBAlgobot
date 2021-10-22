#!/usr/bin/env python3

#import modules
from ibapi.client import EClient
from ibapi.wrapper import EWrapper
import sys
import os

sys.path.append('/home/')

# types
from ibapi.common import * # @UnusedWildImport
from ibapi.order_condition import * # @UnusedWildImport
from ibapi.contract import * # @UnusedWildImport
from ibapi.order import * # @UnusedWildImport
from ibapi.order_state import * # @UnusedWildImport
from ibapi.execution import Execution
from ibapi.execution import ExecutionFilter
from ibapi.commission_report import CommissionReport
from ibapi.ticktype import * # @UnusedWildImport
# from mktDataEnum import *
from ibapi.tag_value import TagValue
import logging
import datetime
import pandas as pd
import pprint

module_logger = logging.getLogger('IBTradingBot.twsapi')

#define IB API class
class IBapi(EWrapper, EClient):
	filepath = '/Users/derrickike/Documents/Trading/IBKR_Algo/'
	def __init__(self):
		EClient.__init__(self, self)
		self.history = [] #Initialize variable to store candle
		self.accountData = {}
		self.marketData = []
		self.deets = []
		self.portfolio = []
		self.openOrders = []
		self.openOrderStatus = []
		self.permId2ord = {}
		self.twsTime = 0
		self.tradingHours = False
		self.optParams = []
		self.executions = []
		self.commissions = []
		self.orders = {}
		self.accountLogUpdate = None
		self.connected = False
		self.logger = logging.getLogger('IBTradingBot.twsapi.IBapi')

	def currentTime(self, t):
		# t = time.ctime(twsTime)
		self.twsTime = t

	def nextValidId(self, orderId: int):
		super().nextValidId(orderId)

		self.logger.debug("setting nextValidOrderId: %d", orderId)
		self.nextValidOrderId = orderId
		self.logger.info("NextValidId: %s", orderId)
		self.connected = True

	def nextOrderId(self):
		oid = self.nextValidOrderId
		self.nextValidOrderId += 1
		return oid

	def historicalData(self, reqID, bar):
		# print(f'Time: {bar.date} Close: {bar.close}')
		self.history.append([bar.date, bar.close])

	def accountSummary(self, reqID: int, account: str, tag: str, value: str, currency: str):
		super().accountSummary(reqID, account, tag, value, currency)
		# print("AccountSummary. ReqId:", reqID, "Account:", account, "Tag: ", tag, "Value:", value, "Currency:", currency)

	def updateAccountTime(self, timeStamp: str):
		super().updateAccountTime(timeStamp)
		self.logger.info("UpdateAccountTime. Time: %s", timeStamp)
		# print("UpdateAccountTime. Time:", timeStamp)
		self.accountData.update({"Time": timeStamp})

	def updateAccountValue(self, key: str, val: str, currency: str, accountName: str):
		super().updateAccountValue(key, val, currency, accountName)
		# print("UpdateAccountValue. Key:", key, "Value:", val, "Currency:", currency, "AccountName:", accountName)
		# self.accountData.clear()
		self.accountData.update({"AccountName": accountName})
		self.accountData.update({"Currency": currency})
		self.accountData.update({key: val})



		return(key,val,currency,accountName)

	#Update Portfolio
	def updatePortfolio(self, contract: Contract, position: float, marketPrice: float,
	marketValue: float, averageCost: float, unrealizedPNL: float, realizedPNL: float, accountName: str):
		super().updatePortfolio(Contract, position, marketPrice, marketValue, averageCost, unrealizedPNL, realizedPNL, accountName)
		# print("\nUpdatePortfolio.", "Symbol:", contract.symbol, "SecType:", contract.secType, "Exchange:", contract.exchange, "Position:", position, "MarketPrice:", marketPrice, "MarketValue:", marketValue, "AverageCost:", averageCost, "UnrealizedPNL:", unrealizedPNL, "RealizedPNL:", realizedPNL, "AccountName:", accountName)
		# self.portfolio.update({'Symbol': contract.symbol, 'SecType': contract.secType, 'Exchange': contract.exchange, 'Position': position, 'MarketPrice': marketPrice, 'MarketValue': marketValue, 'AverageCost': averageCost, 'UnrealizedPNL': unrealizedPNL, 'RealizedPNL': realizedPNL, 'AccountName':accountName})
		data = [contract.symbol, contract.secType, contract.strike, contract.lastTradeDateOrContractMonth, contract.right, position, marketPrice, marketValue, averageCost, unrealizedPNL, realizedPNL, accountName]
		flag = False
		for i in range(len(self.portfolio)):
			if (self.portfolio[i][0] == contract.symbol) and (self.portfolio[i][1] == contract.secType) and (self.portfolio[i][2] == contract.strike) and (self.portfolio[i][3] == contract.lastTradeDateOrContractMonth) and (self.portfolio[i][4] == contract.right):
				self.portfolio[i] = data
				flag = True
		if flag == False:
			self.portfolio.append(data)
		# self.portfolio.append([contract.symbol, contract.secType, contract.exchange,
		# position, marketPrice, marketValue, averageCost, unrealizedPNL, realizedPNL, accountName])


	def mktDepthExchanges(self, depthMktDataDescriptions):
		super().mktDepthExchanges(depthMktDataDescriptions)
		print("MktDepthExchanges:")
		for desc in depthMktDataDescriptions:
			print("DepthMktDataDescription.", desc)



	def accountDownloadEnd(self, accountName: str):
		super().accountDownloadEnd(accountName)
		self.logger.info("AccountDownloadEnd. Account: %s", accountName)
		# print("AccountDownloadEnd. Account:", accountName)
		updateTime = self.accountData.get("Time")
		if (updateTime is not None) and (updateTime > '13:30'):
			self.accountLog()

	def accountLog(self):
		todayDate = datetime.date.today()

		if (self.accountLogUpdate == None) or ((todayDate - self.accountLogUpdate).days >= 1):

			filepath = '/Users/derrickike/Documents/Trading/IBKR_Algo/'
			accoutLogOutPath = filepath + 'AccountLog.csv'
			# self.totalReturn = round((self.NetLiqVal - startingCash)/startingCash, 4)
			# self.spxReturn = round((self.spx - self.spxStart)/self.spxStart, 4)
			# data = [logDate, self.NetLiqVal, self.totalCash, self.unrealPNL, self.realPNL, self.excessLiq, self.maintMargin, self.spx, self.vix, self.shortDelta, self.totalReturn, self.spxReturn]

			logDate = todayDate.strftime("%Y-%m-%d")

			data = [logDate, self.accountData.get('NetLiquidation'),
			self.accountData.get('TotalCashBalance'),
			self.accountData.get('UnrealizedPnL'),
			self.accountData.get('RealizedPnL'),
			self.accountData.get('ExcessLiquidity'),
			self.accountData.get('MaintMarginReq')]
			# app.accountData.get('SPX'),
			# app.accountData.get('VIX'),
			# app.accountData.get('ShortDelta')]
			# app.accountData.get('total return')]
			# app.accountData.get('spx return')]
			accountDF = pd.DataFrame([data], columns=['Date','NetLiqVal','TotalCash','UnrealPNL','RealPNL','ExcessLiquidity','maintMargin'])

			accountDF.to_csv(accoutLogOutPath, mode='a', index=False, header=(not os.path.exists(accoutLogOutPath)))

			# print(accountDF)
			self.logger.info('Account Log:\n%s',accountDF)

			self.accountLogUpdate = todayDate

	#function to update market data array with new incoming tick data
	def mktDataUpdate(self, reqID, ticktype, mktData):
		tickIndex = ticktype + 1
		updateFlag = False

		for i in range(len(self.marketData)):
			if (self.marketData[i][0] == reqID):
				self.marketData[i][tickIndex] = mktData
				updateFlag = True

		if updateFlag == False:
			data = [None] * 101
			data[0] = reqID
			data[tickIndex] = mktData
			# print(f'\nMarket Data Update: \n{data}')
			self.marketData.append(data)

		# self.logger.debug('mktdataUpdate: \n%s', self.marketData)
		# print(f'\nMarket Data: \n{self.marketData}')

	# ! [tickprice]
	def tickPrice(self, reqID: TickerId, tickType: TickType, price: float, attrib: TickAttrib):
		super().tickPrice(reqID, tickType, price, attrib)
		# print("\nTickPrice. TickerId:", reqID, "tickType:", tickType, "Price:", price,
		# "CanAutoExecute:", attrib.canAutoExecute, "PastLimit:", attrib.pastLimit, end=' ')
		self.mktDataUpdate(reqID, tickType, price)

	# ! [ticksize]
	def tickSize(self, reqID: TickerId, tickType: TickType, size: int):
		super().tickSize(reqID, tickType, size)
		# print("TickSize. TickerId:", reqID, "TickType:", tickType, "Size:", size)
		self.mktDataUpdate(reqID, tickType, size)

	# ! [tickgeneric]
	def tickGeneric(self, reqID: TickerId, tickType: TickType, value: float):
		super().tickGeneric(reqID, tickType, value)
		# print("TickGeneric. TickerId:", reqID, "TickType:", tickType, "Value:", value)
		self.mktDataUpdate(reqID, tickType, value)
	# ! [tickgeneric]

	# @iswrapper
	# ! [tickstring]
	def tickString(self, reqID: TickerId, tickType: TickType, value: str):
		super().tickString(reqID, tickType, value)
		# print("TickString. TickerId:", reqID, "Type:", tickType, "Value:", value)
		self.mktDataUpdate(reqID, tickType, value)
	# ! [tickstring]

	def tickSnapshotEnd(self, reqID: int):
		super().tickSnapshotEnd(reqID)
		# print("TickSnapshotEnd. TickerId:", reqID)

	def tickOptionComputation(self, reqID: TickerId, tickType: TickType, impliedVol: float,
	delta: float, optPrice: float, pvDividend: float, gamma: float, vega: float, theta: float, undPrice: float):
		super().tickOptionComputation(reqID, tickType, impliedVol, delta, optPrice, pvDividend, gamma, vega, theta, undPrice)
		# print("TickOptionComputation. TickerId:", reqID, "TickType:", tickType, "ImpliedVolatility:",
		# impliedVol, "Delta:", delta, "OptionPrice:", optPrice, "pvDividend:", pvDividend, "Gamma: ", gamma, "Vega:",
		# vega, "Theta:", theta, "UnderlyingPrice:", undPrice)
		greeks = [impliedVol, delta, optPrice, pvDividend, gamma, vega, theta, undPrice]
		for i in range(len(greeks)):
			if (greeks[i] is not None):
				greeks[i] = round(greeks[i], 3)
		self.mktDataUpdate(reqID, tickType, greeks)

	def securityDefinitionOptionParameter(self, reqID, exchange, underlyingConId, tradingClass, multiplier, expirations, strikes):
		super().securityDefinitionOptionParameter(reqID, exchange, underlyingConId, tradingClass, multiplier, expirations, strikes)
		# print("SecurityDefinitionOptionParameter.", "ReqId:", reqID, "Exchange:", exchange, "Underlying conId:",
		# underlyingConId, "TradingClass:", tradingClass, "Multiplier:", multiplier, "Expirations:", expirations, "Strikes:", str(strikes))
		# self.optParams = []
		self.optParams.append([reqID, exchange, underlyingConId, tradingClass, multiplier, expirations, strikes])

	def contractDetails(self, reqID, contractDetails):
		super().contractDetails(reqID, contractDetails)
		# print("ContractDetails.", "ReqId:", reqID, "Contract Details:", contractDetails.contract.lastTradeDateOrContractMonth, contractDetails.contract.strike, contractDetails.contract.right)
		# print(contractDetails.contract.conId, contractDetails.contract.symbol, contractDetails.contract.lastTradeDateOrContractMonth, contractDetails.contract.strike, contractDetails.contract.right, contractDetails.underConId)
		# self.deets = []

		self.deets.append([reqID, contractDetails.contract.conId, contractDetails.contract.symbol, contractDetails.contract.lastTradeDateOrContractMonth,
		contractDetails.contract.strike, contractDetails.contract.right, contractDetails.underConId])
		# return (contractDetails)

	def error(self, id, errorCode, errorMsg):
		# super().error(id, errorCode, errorMsg)
		# print(f'ID: {id} Code: {errorCode} Message: {errorMsg}')
		self.logger.error('ID: %s Code: %s Message: %s', id, errorCode, errorMsg)
		if errorCode == 504:
			self.connected = False

	def openOrder(self, orderId: OrderId, contract: Contract, order: Order, orderState: OrderState):
		super().openOrder(orderId, contract, order, orderState)
		# print("\nOpenOrder. PermId: ", order.permId, "ClientId:", order.clientId, " OrderId:", orderId, "Account:", order.account, "Symbol:", contract.symbol, "SecType:", contract.secType, "Exchange:", contract.exchange, "Action:", order.action, "OrderType:", order.orderType, "TotalQty:", order.totalQuantity, "CashQty:", order.cashQty, "LmtPrice:", order.lmtPrice, "AuxPrice:", order.auxPrice, "Status:", orderState.status)

		order.contract = contract
		self.permId2ord[order.permId] = order

		self.openOrders.append([order.permId, order.clientId, order.orderRef, order.parentId, orderId, order.account, contract.symbol,
		contract.secType, contract.exchange, order.action, order.orderType, order.totalQuantity, order.cashQty,
		order.lmtPrice, order.auxPrice, orderState.status])
		self.orders.update({orderId:order})


	def openOrderEnd(self):
		super().openOrderEnd()
		# print("OpenOrderEnd")
		self.logger.debug("Received %d openOrders", len(self.permId2ord))

	def orderStatus(self, orderId: OrderId, status: str, filled: float,
                    remaining: float, avgFillPrice: float, permId: int,
                    parentId: int, lastFillPrice: float, clientId: int,
                    whyHeld: str, mktCapPrice: float):
		super().orderStatus(orderId, status, filled, remaining, avgFillPrice, permId, parentId, lastFillPrice, clientId, whyHeld, mktCapPrice)
		# print("\nOrderStatus. Id:", orderId, "Status:", status, "Filled:", filled,
		# "Remaining:", remaining, "AvgFillPrice:", avgFillPrice,
		# "PermId:", permId, "ParentId:", parentId, "LastFillPrice:",
		# lastFillPrice, "ClientId:", clientId, "WhyHeld:", whyHeld, "MktCapPrice:", mktCapPrice)

	def tradeLog(self, data):
		filename = 'TradeLog.csv'
		outputPath = self.filepath + filename
		tradelogDF = pd.DataFrame(data, columns=['Account','Time','clientId','permId','OrderId','ExecId','Symbol','SecType','Exchange', 'Side', 'Shares', 'Price',
		'Liquidation', 'CumQty', 'AvgPrice', 'OrderRef', 'EvRule', 'EvMultiplier', 'ModelCode', 'LastLiquidity'])
		tradelogDF.to_csv(filename, mode='a', header=(not os.path.exists(outputPath)))

	def execDetails(self, reqId: int, contract: Contract, execution: Execution):
		super().execDetails(reqId, contract, execution)
		# print("ExecDetails. ReqId:", reqId, "Symbol:", contract.symbol, "SecType:", contract.secType, "Currency:", contract.currency, execution)
		# pprint.pprint(execution.__dict__)
		# data = execution.__dict__.values()
		data = [execution.acctNumber, execution.time, execution.clientId, execution.permId, execution.orderId, execution.execId, contract.symbol, contract.secType, execution.exchange,
		execution.side, execution.shares, execution.price, execution.liquidation, execution.cumQty, execution.avgPrice, execution.orderRef, execution.evRule, execution.evMultiplier,
		execution.modelCode, execution.lastLiquidity]
		# print('Execution Details: \n',data)
		execStatus = pd.DataFrame([data], columns=['AcctNo','ExecTime','ClientId',
		'PermId','OrderId','ExecId','Symbol','SecType','Exchange','Side','Shares',
		'Price','Liquidation','cumQty','AvgPrice','OrderRef','evRule','evMultiplier',
		'ModelCode','lastLiquidity'])
		self.executions.append(data)
		self.logger.info('Execution Details: \n%s\n', execStatus)
		self.tradeLog([data])

	def commissionReport(self, commissionReport: CommissionReport):
		super().commissionReport(commissionReport)
		# print("CommissionReport.", commissionReport)
