# Miswex 
Miswex is an AI-powered crypto trading agent that executes trades autonomously using strategies learned through machine learning. It does not rely on hard-coded rules or manual inputs. Once trained, the AI selects and applies the best strategy based on current market conditions and manages entries, exits, scaling, and risk automatically.
(Github Link not uploaded in order to prevent any


## What Problem Miswex Solves
Most traders use rigid strategies that stop working when the market changes. Indicators, emotions, and fixed rules lead to inconsistent performance. Miswex solves this by learning market behavior directly from historical data and adapting its decisions dynamically.


## How Miswex Works
### Miswex consists of two main components:
 #### Training Engine
The AI was trained using historical market data to discover profitable strategies.
Training setup:
Total data used: 5 months
Training: 3 months
Validation: 1 month
Test (unseen): 1 month
Additional forward test: recent 15 days (live-like conditions)
The model showed strong performance on both unseen data and recent market data.
#### Assets trained:
(These were more profitable compared to others and more volatile)

ADA

SOL

DOGE
#### Timeframes:
5 minute

15 minute

1 hour

#### Evolution configuration:
51 genomes per coin per timeframe

Population size: 99 per genome

#### The AI evolved strategies by optimizing:
Entry logic

Stop-loss & take-profit

Trailing exits

Scaling behavior

Market regime adaptation

Bitcoin influence weighting

#### Training refinement:  
During early training, the AI discovered multiple loopholes and unrealistic patterns that inflated results. These were systematically filtered out through continuous fine-tuning, adding stricter constraints, validation checks, and logic filters. Each training cycle improved robustness and realism.


### AI Agent (Live Execution)
The GitHub repository includes a dedicated AI Agent folder responsible for live trading.
#### This agent:
Loads selected AI-generated strategies

Reads real-time market data

Executes trades based on strategy logic

Manages positions during live trading

#### Workflow:
AI trains and identifies top strategies per genome

Strategies are backtested for performance and stability

Strong coin + timeframe combinations are chosen

Chosen strategies are deployed into the trading engine


## Key Features
Adaptive strategy selection

Multi-timeframe intelligence

Learns when to follow BTC (not hard-coded)

Regime-aware trading (trend, chop, high volatility)

Micro-timeframe support (1m) for precision entries

Fully autonomous execution


## Vision
Miswex aims to become a self-evolving trading intelligence that can survive all market conditions by learning from data instead of relying on fragile rules.


##  Repository Structure
/training → Contains all experiments, tests, strategy generations, logs, and model checkpoints

/ai-agent → Live trading execution engine


## Status
Training completed

Strategies generated

Forward tested on recent data

Live execution engine ready
