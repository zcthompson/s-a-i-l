"""Sample data seed script for S-A-I-L (Sales Analytics and Intelligence Launchpad).

Populates the database with example use cases for demonstration/testing.
Run with: python -m backend.seed

Usage:
    python -m backend.seed                          # seed with defaults
    python -m backend.seed --reset                  # reset DB then seed
    python -m backend.seed --json output.json       # also export to JSON
"""

import argparse
import json
import re
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.orm import Session

from backend.auth import hash_password
from backend.models.customer_knowledge import CustomerKnowledge
from backend.models.customer_technology import CustomerTechnology
from backend.models.sales_note import (
    SalesNote,
    sales_note_technologies,
    sales_note_use_cases,
)
from backend.models.technology_dependency import TechnologyDependency
from backend.models.use_case import (
    AIPrediction,
    Branch,
    Customer,
    CustomerAssessment,
    CustomerUser,
    Department,
    UseCase,
    User,
    get_session,
)

CUSTOMERS = [
    {
        "name": "Acme Manufacturing",
        "description": "Large-scale manufacturing with global operations",
        "departments": [
            {
                "name": "Operations",
                "use_cases": [
                    {
                        "title": "Predictive Maintenance for Manufacturing Equipment",
                        "description": "Use sensor data from CNC machines to predict equipment failures before they occur, reducing unplanned downtime.",
                        "goals": ["Reduce unplanned downtime by 30%", "Extend equipment lifespan by 15%", "Optimize maintenance scheduling"],
                        "challenges": ["Sensor data quality varies across equipment", "Historical failure data is sparse"],
                        "pain_points": ["Average 48 hours unplanned downtime per month", "$200K+ in lost production per event"],
                        "impact_category": "cost", "estimated_savings": 500000, "estimated_revenue": 0, "timeline_estimate": "medium",
                        "status": "completed", "scored": True, "overall_score": 72.5,
                    },
                    {
                        "title": "Quality Analytics Dashboard",
                        "description": "Real-time quality metrics dashboard aggregating inspection data, defect rates, and yield trends across all production lines.",
                        "goals": ["Centralize quality metrics in one dashboard", "Reduce defect escape rate to under 1%", "Enable shift-by-shift quality comparison"],
                        "challenges": ["Data sources are fragmented across systems", "Need real-time data aggregation"],
                        "pain_points": ["Quality data siloed in separate spreadsheets", "Leadership lacks visibility into quality trends"],
                        "impact_category": "quality", "estimated_savings": 200000, "estimated_revenue": 50000, "timeline_estimate": "short",
                        "status": "completed", "scored": True, "overall_score": 68.0,
                    },
                ],
            },
            {
                "name": "Supply Chain",
                "use_cases": [
                    {
                        "title": "Demand Forecasting for Supply Chain",
                        "description": "ML model to predict product demand across regions, optimizing inventory levels and reducing both stockouts and overstock.",
                        "goals": ["Improve forecast accuracy to 85%", "Reduce inventory carrying costs by 20%", "Minimize stockout events"],
                        "challenges": ["Seasonal patterns are complex and shifting", "External factors are hard to model"],
                        "pain_points": ["15% stockout rate on key products", "Manual forecasting takes 2 weeks per cycle"],
                        "impact_category": "cost", "estimated_savings": 750000, "estimated_revenue": 200000, "timeline_estimate": "long",
                        "status": "completed", "scored": True, "overall_score": 50.0,
                    },
                    {
                        "title": "Vendor Risk Analytics",
                        "description": "AI-driven vendor risk scoring that evaluates financial health, delivery reliability, and geopolitical exposure of suppliers.",
                        "goals": ["Quantify vendor risk scores automatically", "Alert on risk threshold breaches", "Diversify high-risk supplier base"],
                        "challenges": ["Limited vendor financial data", "Risk model needs continuous calibration"],
                        "pain_points": ["No systematic vendor risk assessment", "Single-source dependency on critical components"],
                        "impact_category": "risk", "estimated_savings": 300000, "estimated_revenue": 0, "timeline_estimate": "medium",
                        "status": "completed", "scored": True, "overall_score": 54.0,
                    },
                ],
            },
            {
                "name": "Engineering",
                "use_cases": [
                    {
                        "title": "AI-Driven Design Optimization",
                        "description": "Generative AI tool to optimize product designs for manufacturability, cost reduction, and performance enhancement.",
                        "goals": ["Reduce design iteration cycles by 50%", "Identify cost-down opportunities automatically", "Improve first-pass yield"],
                        "challenges": ["Need domain-specific training data", "Integrating with existing CAD tools"],
                        "pain_points": ["Design changes cost $50K+ per revision", "Cross-functional alignment on designs takes weeks"],
                        "impact_category": "cost", "estimated_savings": 400000, "estimated_revenue": 100000, "timeline_estimate": "long",
                        "status": "completed", "scored": True, "overall_score": 55.0,
                    },
                ],
            },
            {
                "name": "Procurement",
                "use_cases": [
                    {
                        "title": "Intelligent Sourcing Recommendations",
                        "description": "AI system that recommends optimal suppliers based on cost, quality, delivery reliability, and sustainability metrics.",
                        "goals": ["Reduce procurement cycle time by 30%", "Achieve 10% cost savings through better sourcing", "Track supplier sustainability scores"],
                        "challenges": ["Supplier data quality is inconsistent", "Multi-criteria optimization is complex"],
                        "pain_points": ["Procurement team spends 60% time on manual sourcing", "Cost negotiation lacks data-driven leverage"],
                        "impact_category": "cost", "estimated_savings": 600000, "estimated_revenue": 0, "timeline_estimate": "medium",
                        "status": "completed", "scored": True, "overall_score": 56.0,
                    },
                ],
            },
            {
                "name": "Quality",
                "use_cases": [
                    {
                        "title": "Automated Defect Classification",
                        "description": "Computer vision system to automatically classify defects from production line images and categorize by root cause.",
                        "goals": ["Automate 90% of defect classification", "Reduce manual QA labor by 40%", "Enable root-cause trend analysis"],
                        "challenges": ["Diverse defect types require large labeled dataset", "Factory floor lighting variability"],
                        "pain_points": ["QA team manually inspects 500 parts daily", "Defect classification inconsistency between inspectors"],
                        "impact_category": "quality", "estimated_savings": 250000, "estimated_revenue": 0, "timeline_estimate": "short",
                        "status": "completed", "scored": True, "overall_score": 65.0,
                    },
                ],
            },
            {
                "name": "Production Planning",
                "use_cases": [
                    {
                        "title": "AI Production Schedule Optimizer",
                        "description": "Optimization engine that creates production schedules balancing capacity, demand, changeover costs, and delivery deadlines.",
                        "goals": ["Increase production utilization to 90%", "Reduce changeover downtime by 25%", "Meet 98% on-time delivery"],
                        "challenges": ["Dynamic schedule changes are common", "Multiple constraints must be balanced"],
                        "pain_points": ["Manual scheduling takes 4 hours daily", "Schedule conflicts cause $100K+ in lost output"],
                        "impact_category": "efficiency", "estimated_savings": 350000, "estimated_revenue": 0, "timeline_estimate": "medium",
                        "status": "completed", "scored": True, "overall_score": 52.0,
                    },
                ],
            },
            {
                "name": "Safety",
                "use_cases": [
                    {
                        "title": "Workplace Safety Monitoring",
                        "description": "IoT and AI system to monitor workplace safety conditions, predict hazards, and ensure compliance with safety regulations.",
                        "goals": ["Reduce workplace incidents by 50%", "Automate safety compliance reporting", "Enable real-time hazard detection"],
                        "challenges": ["Sensor coverage gaps", "Integration with existing safety management systems"],
                        "pain_points": ["Safety incidents cost $500K+ annually", "Manual safety audits miss 40% of hazards"],
                        "impact_category": "risk", "estimated_savings": 200000, "estimated_revenue": 0, "timeline_estimate": "medium",
                        "status": "completed", "scored": True, "overall_score": 58.0,
                    },
                ],
            },
            {
                "name": "HR / L&D",
                "use_cases": [
                    {
                        "title": "Workforce Skills Analytics",
                        "description": "AI system to map employee skills, identify skill gaps, and recommend training programs aligned with business needs.",
                        "goals": ["Identify critical skill gaps proactively", "Reduce training costs by 20%", "Improve internal mobility"],
                        "challenges": ["Skills data is not systematically captured", "Change management for new tracking"],
                        "pain_points": ["Hiring for skill gaps costs $200K+ per role", "Training programs have low engagement"],
                        "impact_category": "efficiency", "estimated_savings": 150000, "estimated_revenue": 0, "timeline_estimate": "medium",
                        "status": "completed", "scored": True, "overall_score": 50.0,
                    },
                ],
            },
            {
                "name": "Finance",
                "use_cases": [
                    {
                        "title": "Cost Optimization Analytics",
                        "description": "AI-driven analysis of cost drivers across all operations to identify savings opportunities and optimize resource allocation.",
                        "goals": ["Identify 10% cost reduction opportunities", "Automate cost variance analysis", "Enable scenario planning"],
                        "challenges": ["Cost allocation models are complex", "Data quality across departments varies"],
                        "pain_points": ["Cost overruns of $1M+ per quarter", "No proactive cost monitoring capability"],
                        "impact_category": "cost", "estimated_savings": 500000, "estimated_revenue": 0, "timeline_estimate": "medium",
                        "status": "completed", "scored": True, "overall_score": 62.0,
                    },
                ],
            },
            {
                "name": "IT",
                "use_cases": [
                    {
                        "title": "Manufacturing IT Infrastructure Monitoring",
                        "description": "AI-powered infrastructure monitoring that predicts system failures and optimizes IT resource allocation across manufacturing sites.",
                        "goals": ["Reduce IT downtime by 80%", "Predict system failures before they occur", "Optimize cloud spend"],
                        "challenges": ["Mixed legacy and modern systems", "Cross-site network complexity"],
                        "pain_points": ["IT outages cost $50K+ per hour", "Reactive IT support model"],
                        "impact_category": "efficiency", "estimated_savings": 200000, "estimated_revenue": 0, "timeline_estimate": "short",
                        "status": "completed", "scored": True, "overall_score": 58.0,
                    },
                ],
            },
            {
                "name": "Customer Relations",
                "use_cases": [
                    {
                        "title": "B2B Customer Satisfaction Analytics",
                        "description": "AI analysis of B2B customer interactions, order patterns, and feedback to predict satisfaction and identify retention risks.",
                        "goals": ["Predict customer churn with 80% accuracy", "Personalize B2B engagement", "Improve NPS by 15 points"],
                        "challenges": ["B2B feedback is sparse", "Multiple stakeholders per account"],
                        "pain_points": ["10% B2B customer attrition annually", "No proactive retention strategy"],
                        "impact_category": "revenue", "estimated_savings": 0, "estimated_revenue": 400000, "timeline_estimate": "medium",
                        "status": "completed", "scored": True, "overall_score": 54.0,
                    },
                ],
            },
            {
                "name": "Sustainability",
                "use_cases": [
                    {
                        "title": "Energy Consumption Optimization",
                        "description": "AI system to monitor and optimize energy consumption across manufacturing facilities, reducing costs and carbon footprint.",
                        "goals": ["Reduce energy costs by 15%", "Achieve carbon neutrality tracking", "Comply with environmental regulations"],
                        "challenges": ["Energy data granularity varies", "Production schedule constraints"],
                        "pain_points": ["Energy costs represent 8% of manufacturing costs", "No real-time energy visibility"],
                        "impact_category": "cost", "estimated_savings": 300000, "estimated_revenue": 0, "timeline_estimate": "long",
                        "status": "completed", "scored": True, "overall_score": 52.0,
                    },
                ],
            },
        ],
    },
    {
        "name": "GlobalBank Financial Services",
        "description": "Regional bank with digital transformation initiatives",
        "departments": [
            {
                "name": "Finance",
                "use_cases": [
                    {
                        "title": "Fraud Detection for Financial Transactions",
                        "description": "Real-time anomaly detection system to identify potentially fraudulent transactions across payment channels.",
                        "goals": ["Detect 95%+ of fraudulent transactions in real-time", "Reduce false positive rate to under 1%", "Automate investigation workflow"],
                        "challenges": ["Adversarial actors evolve quickly", "Balancing fraud detection with customer experience"],
                        "pain_points": ["$1M+ in annual fraud losses", "Current rule-based system has 30% false positive rate"],
                        "impact_category": "risk", "estimated_savings": 1000000, "estimated_revenue": 0, "timeline_estimate": "medium",
                        "status": "completed", "scored": True, "overall_score": 65.0,
                    },
                    {
                        "title": "AI-Powered Credit Risk Assessment",
                        "description": "Machine learning model to assess creditworthiness using alternative data sources, enabling faster loan decisions.",
                        "goals": ["Reduce loan approval time from 5 days to 2 hours", "Include underbanked populations", "Maintain default rates below 3%"],
                        "challenges": ["Regulatory constraints on fair lending", "Model interpretability requirements"],
                        "pain_points": ["High volume of manual credit reviews", "Lost business from slow approval process"],
                        "impact_category": "risk", "estimated_savings": 200000, "estimated_revenue": 500000, "timeline_estimate": "long",
                        "status": "completed", "scored": True, "overall_score": 44.0,
                    },
                ],
            },
            {
                "name": "IT",
                "use_cases": [
                    {
                        "title": "Automated Regulatory Reporting",
                        "description": "AI system to automatically compile and format regulatory reports from transaction data, reducing manual effort and errors.",
                        "goals": ["Reduce report preparation time by 80%", "Achieve 99.9% accuracy in regulatory submissions", "Enable real-time compliance monitoring"],
                        "challenges": ["Regulatory requirements change frequently", "Strict audit trail requirements"],
                        "pain_points": ["Compliance team spends 40% time on manual reporting", "Two weeks to compile quarterly reports"],
                        "impact_category": "compliance", "estimated_savings": 350000, "estimated_revenue": 0, "timeline_estimate": "medium",
                        "status": "completed", "scored": True, "overall_score": 50.0,
                    },
                ],
            },
            {
                "name": "Risk Management",
                "use_cases": [
                    {
                        "title": "Model Risk Validation",
                        "description": "AI-powered validation framework to assess model risk across all quantitative models used in lending, trading, and risk management.",
                        "goals": ["Reduce model validation cycle time by 50%", "Automate back-testing of model assumptions", "Maintain regulatory compliance"],
                        "challenges": ["Complex model architectures", "Limited historical performance data for new models"],
                        "pain_points": ["Model validation takes 6+ weeks per cycle", "Manual testing is error-prone"],
                        "impact_category": "risk", "estimated_savings": 250000, "estimated_revenue": 0, "timeline_estimate": "long",
                        "status": "completed", "scored": True, "overall_score": 52.0,
                    },
                ],
            },
            {
                "name": "Trading",
                "use_cases": [
                    {
                        "title": "Algorithmic Trading Strategy Discovery",
                        "description": "AI system that identifies and tests new algorithmic trading strategies using historical market data and machine learning.",
                        "goals": ["Discover profitable trading patterns", "Back-test strategies rapidly", "Reduce strategy development cycle to days"],
                        "challenges": ["Market data noise", "Overfitting risk"],
                        "pain_points": ["Strategy development takes 3+ months", "Manual back-testing is incomplete"],
                        "impact_category": "revenue", "estimated_savings": 0, "estimated_revenue": 2000000, "timeline_estimate": "long",
                        "status": "completed", "scored": True, "overall_score": 55.0,
                    },
                ],
            },
            {
                "name": "Compliance",
                "use_cases": [
                    {
                        "title": "AML Transaction Monitoring",
                        "description": "AI-powered anti-money laundering monitoring that detects suspicious transaction patterns and automates suspicious activity reporting.",
                        "goals": ["Reduce false positives by 70%", "Detect complex money laundering patterns", "Automate SAR filing"],
                        "challenges": ["Evolving money laundering techniques", "Regulatory scrutiny on model decisions"],
                        "pain_points": ["AML team manually reviews 5000 alerts weekly", "95% false positive rate"],
                        "impact_category": "risk", "estimated_savings": 500000, "estimated_revenue": 0, "timeline_estimate": "medium",
                        "status": "completed", "scored": True, "overall_score": 58.0,
                    },
                ],
            },
            {
                "name": "Wealth Management",
                "use_cases": [
                    {
                        "title": "Portfolio Optimization Engine",
                        "description": "AI-driven portfolio optimization that balances risk, return, and client preferences for personalized wealth management advice.",
                        "goals": ["Improve portfolio returns by 5%", "Personalize investment recommendations", "Reduce advisor workload by 30%"],
                        "challenges": ["Client risk profiles are complex", "Regulatory constraints on recommendations"],
                        "pain_points": ["Advisor capacity limits growth", "Manual portfolio rebalancing is slow"],
                        "impact_category": "revenue", "estimated_savings": 0, "estimated_revenue": 1500000, "timeline_estimate": "long",
                        "status": "completed", "scored": True, "overall_score": 54.0,
                    },
                ],
            },
            {
                "name": "Customer Success",
                "use_cases": [
                    {
                        "title": "Banking Customer Churn Prediction",
                        "description": "Predictive model to identify customers at risk of leaving the bank and recommend personalized retention actions.",
                        "goals": ["Reduce customer churn by 20%", "Predict churn 90 days in advance", "Personalize retention offers"],
                        "challenges": ["Customer behavior data is multi-channel", "Retention interventions must be timely"],
                        "pain_points": ["Customer acquisition costs 5x retention costs", "Reactive rather than proactive retention"],
                        "impact_category": "revenue", "estimated_savings": 0, "estimated_revenue": 800000, "timeline_estimate": "medium",
                        "status": "completed", "scored": True, "overall_score": 52.0,
                    },
                ],
            },
            {
                "name": "HR / L&D",
                "use_cases": [
                    {
                        "title": "Financial Services Workforce Analytics",
                        "description": "AI analysis of workforce trends in banking to optimize talent acquisition, retention, and skills development.",
                        "goals": ["Reduce time-to-hire by 25%", "Predict attrition risk", "Align skills with digital transformation"],
                        "challenges": ["Specialized skill sets in finance", "Competitive talent market"],
                        "pain_points": ["Key role vacancies average 4 months", "Skills gaps in digital banking"],
                        "impact_category": "efficiency", "estimated_savings": 150000, "estimated_revenue": 0, "timeline_estimate": "medium",
                        "status": "completed", "scored": True, "overall_score": 50.0,
                    },
                ],
            },
            {
                "name": "Operations",
                "use_cases": [
                    {
                        "title": "Branch Network Optimization",
                        "description": "AI analysis of branch performance, foot traffic, and customer demographics to optimize branch network layout and resource allocation.",
                        "goals": ["Optimize branch profitability", "Reduce underperforming branches by 20%", "Improve branch customer experience"],
                        "challenges": ["Real estate constraints", "Community relationship considerations"],
                        "pain_points": ["40% of branches are underperforming", "Branch strategy is not data-driven"],
                        "impact_category": "cost", "estimated_savings": 400000, "estimated_revenue": 0, "timeline_estimate": "long",
                        "status": "completed", "scored": True, "overall_score": 48.0,
                    },
                ],
            },
            {
                "name": "Finance - Corporate",
                "use_cases": [
                    {
                        "title": "Financial Statement Fraud Detection",
                        "description": "AI system that detects anomalies in corporate financial statements to support credit underwriting and investment decisions.",
                        "goals": ["Identify financial statement red flags", "Reduce credit losses by 15%", "Automate initial financial analysis"],
                        "challenges": ["Sophisticated fraud techniques", "Diverse accounting standards"],
                        "pain_points": ["Credit losses of $500K+ per quarter", "Manual financial analysis is slow"],
                        "impact_category": "risk", "estimated_savings": 300000, "estimated_revenue": 0, "timeline_estimate": "medium",
                        "status": "completed", "scored": True, "overall_score": 53.0,
                    },
                ],
            },
                        {                "name": "IT Infrastructure",
                "use_cases": [
                                {                        "title": "Core Banking System Anomaly Detection",
                        "description": "AI monitoring of core banking system transactions and operations to detect anomalies, errors, and performance issues.",
                        "goals": ["Reduce system downtime by 90%", "Detect data integrity issues early", "Predict capacity constraints"],
                        "challenges": ["Legacy system integration", "High-volume transaction processing"],
                        "pain_points": ["System downtime costs $200K+ per hour", "Manual monitoring misses 60% of issues"],
                        "impact_category": "efficiency", "estimated_savings": 250000, "estimated_revenue": 0, "timeline_estimate": "short",
                        "status": "completed", "scored": True, "overall_score": 55.0,
                    },
                ],
            },
            {
                "name": "Investor Relations",
                "use_cases": [
                    {
                        "title": "Market Sentiment Analysis",
                        "description": "AI analysis of market sentiment from news, social media, and earnings calls to support investor relations strategy.",
                        "goals": ["Monitor investor sentiment in real-time", "Predict stock price impact of events", "Support earnings call preparation"],
                        "challenges": ["Sentiment data is noisy", "Regulatory communication constraints"],
                        "pain_points": ["Investor relations team lacks sentiment monitoring", "Reactive rather than proactive investor communication"],
                        "impact_category": "revenue", "estimated_savings": 0, "estimated_revenue": 500000, "timeline_estimate": "medium",
                        "status": "completed", "scored": True, "overall_score": 50.0,
                    },
                ],
            },
        ],
    },
    {
        "name": "TechCorp Solutions",
        "description": "Enterprise software company scaling rapidly",
        "departments": [
            {
                "name": "Customer Success",
                "use_cases": [
                    {
                        "title": "Automated Customer Support Triage",
                        "description": "NLP-based system to categorize and route customer support tickets to the right department, with suggested responses.",
                        "goals": ["Reduce ticket handling time by 40%", "Improve first-contact resolution rate", "Lower support costs per ticket"],
                        "challenges": ["Multi-language support required", "Domain-specific terminology varies"],
                        "pain_points": ["Average 4-hour wait time for support", "60% of tickets are routine questions"],
                        "impact_category": "time", "estimated_savings": 250000, "estimated_revenue": 100000, "timeline_estimate": "short",
                        "status": "completed", "scored": True, "overall_score": 72.0,
                    },
                    {
                        "title": "Churn Prediction and Retention",
                        "description": "Predictive model to identify at-risk customers and recommend personalized retention actions.",
                        "goals": ["Reduce customer churn by 15%", "Predict churn with 90% accuracy 60 days in advance", "Prioritize retention efforts"],
                        "challenges": ["Limited historical churn data", "Multiple factors influence churn decisions"],
                        "pain_points": ["12% annual churn rate costing $500K+ in lost revenue", "No way to predict which customers are at risk"],
                        "impact_category": "revenue", "estimated_savings": 0, "estimated_revenue": 500000, "timeline_estimate": "medium",
                        "status": "completed", "scored": True, "overall_score": 36.0,
                    },
                ],
            },
            {
                "name": "Operations",
                "use_cases": [
                    {
                        "title": "Intelligent Resource Allocation",
                        "description": "AI system to optimize allocation of engineering resources across projects based on skills, availability, and project priorities.",
                        "goals": ["Increase engineer utilization to 85%", "Reduce project delivery delays by 30%", "Balance workload across teams"],
                        "challenges": ["Skills taxonomy is incomplete and evolving", "Personal preferences complicate optimization"],
                        "pain_points": ["30% engineer time wasted on context switching", "Key projects delayed due to resource constraints"],
                        "impact_category": "efficiency", "estimated_savings": 400000, "estimated_revenue": 0, "timeline_estimate": "long",
                        "status": "completed", "scored": True, "overall_score": 50.0,
                    },
                ],
            },
            {
                "name": "DevOps",
                "use_cases": [
                    {
                        "title": "Site Reliability Monitoring with AI Alerts",
                        "description": "AI-powered monitoring that predicts system issues before they impact users, reducing incident response time.",
                        "goals": ["Reduce incident response time by 60%", "Predict 80% of incidents before they occur", "Automate runbook execution"],
                        "challenges": ["Monitoring tool integration is complex", "Alert fatigue from current systems"],
                        "pain_points": ["Average 2-hour incident response time", "On-call engineers burn out at 40%"],
                        "impact_category": "efficiency", "estimated_savings": 200000, "estimated_revenue": 0, "timeline_estimate": "medium",
                        "status": "completed", "scored": True, "overall_score": 54.0,
                    },
                ],
            },
            {
                "name": "Engineering",
                "use_cases": [
                    {
                        "title": "Automated Code Review Assistant",
                        "description": "AI-powered code review tool that identifies bugs, security vulnerabilities, and code quality issues before merge.",
                        "goals": ["Reduce code review time by 50%", "Catch 80% of bugs pre-merge", "Standardize code quality across teams"],
                        "challenges": ["False positives in static analysis", "Developer adoption resistance"],
                        "pain_points": ["Code review takes 2+ days per PR", "Post-merge bugs cost 10x to fix"],
                        "impact_category": "efficiency", "estimated_savings": 150000, "estimated_revenue": 0, "timeline_estimate": "short",
                        "status": "completed", "scored": True, "overall_score": 56.0,
                    },
                ],
            },
            {
                "name": "Finance",
                "use_cases": [
                    {
                        "title": "Expense Fraud Detection",
                        "description": "AI system to detect fraudulent employee expense reports and unusual spending patterns in real-time.",
                        "goals": ["Reduce expense fraud by 80%", "Automate expense approval workflows", "Identify policy violations instantly"],
                        "challenges": ["Diverse expense categories", "Privacy concerns"],
                        "pain_points": ["$200K+ in fraudulent expense claims annually", "Manual review takes 2 weeks per cycle"],
                        "impact_category": "risk", "estimated_savings": 200000, "estimated_revenue": 0, "timeline_estimate": "medium",
                        "status": "completed", "scored": True, "overall_score": 52.0,
                    },
                ],
            },
            {
                "name": "Legal",
                "use_cases": [
                    {
                        "title": "Contract Review Automation",
                        "description": "NLP system to automatically review contracts for risk, compliance issues, and deviations from standard terms.",
                        "goals": ["Reduce contract review time by 70%", "Identify high-risk clauses automatically", "Maintain standard term compliance"],
                        "challenges": ["Diverse contract types", "Legal interpretation nuance"],
                        "pain_points": ["Legal team reviews 500+ contracts per year", "Average review time is 5 days per contract"],
                        "impact_category": "efficiency", "estimated_savings": 100000, "estimated_revenue": 0, "timeline_estimate": "medium",
                        "status": "completed", "scored": True, "overall_score": 50.0,
                    },
                ],
            },
            {
                "name": "Marketing",
                "use_cases": [
                    {
                        "title": "Lead Scoring and Prioritization",
                        "description": "AI-powered lead scoring that ranks prospects by conversion likelihood and recommends optimal engagement strategies.",
                        "goals": ["Improve lead-to-customer conversion by 25%", "Reduce sales cycle by 20%", "Prioritize highest-value prospects"],
                        "challenges": ["Lead data quality varies", "Sales cycle is multi-touch and long"],
                        "pain_points": ["Sales team spends 60% time on low-quality leads", "Lead scoring is manual and subjective"],
                        "impact_category": "revenue", "estimated_savings": 0, "estimated_revenue": 600000, "timeline_estimate": "medium",
                        "status": "completed", "scored": True, "overall_score": 54.0,
                    },
                ],
            },
            {
                "name": "HR / L&D",
                "use_cases": [
                    {
                        "title": "Tech Talent Recruiting Automation",
                        "description": "AI system to streamline tech talent sourcing, screening, and interview scheduling to reduce time-to-hire.",
                        "goals": ["Reduce time-to-hire by 40%", "Automate technical screening", "Improve candidate experience"],
                        "challenges": ["Competitive tech talent market", "Technical assessment validity"],
                        "pain_points": ["Engineering roles average 90 days to fill", "Recruiter capacity limits hiring"],
                        "impact_category": "efficiency", "estimated_savings": 150000, "estimated_revenue": 0, "timeline_estimate": "medium",
                        "status": "completed", "scored": True, "overall_score": 52.0,
                    },
                ],
            },
            {
                "name": "Product Management",
                "use_cases": [
                    {
                        "title": "Product Feature Usage Analytics",
                        "description": "AI analysis of product usage data to identify feature adoption patterns, engagement drivers, and churn signals.",
                        "goals": ["Identify feature adoption trends early", "Predict user churn from usage patterns", "Prioritize feature development"],
                        "challenges": ["Usage data is high-dimensional", "Attribution is complex"],
                        "pain_points": ["Feature decisions are based on gut feeling", "No systematic usage analytics"],
                        "impact_category": "revenue", "estimated_savings": 0, "estimated_revenue": 300000, "timeline_estimate": "short",
                        "status": "completed", "scored": True, "overall_score": 58.0,
                    },
                ],
            },
            {
                "name": "IT",
                "use_cases": [
                    {
                        "title": "Software Asset Management",
                        "description": "AI system to optimize software licenses, track usage patterns, and prevent overspending on unnecessary tools.",
                        "goals": ["Reduce software spend by 15%", "Track license utilization", "Prevent compliance violations"],
                        "challenges": ["Decentralized software purchases", "Usage tracking is incomplete"],
                        "pain_points": ["$500K+ wasted on unused licenses annually", "No central software inventory"],
                        "impact_category": "cost", "estimated_savings": 200000, "estimated_revenue": 0, "timeline_estimate": "short",
                        "status": "completed", "scored": True, "overall_score": 55.0,
                    },
                ],
            },
            {
                "name": "Data Science",
                "use_cases": [
                    {
                        "title": "ML Model Performance Monitoring",
                        "description": "AI system to monitor production ML model performance, detect drift, and trigger retraining automatically.",
                        "goals": ["Detect model drift within 24 hours", "Automate model retraining triggers", "Maintain model accuracy above 90%"],
                        "challenges": ["Multi-model portfolio complexity", "Drift detection is nuanced"],
                        "pain_points": ["Model degradation goes unnoticed for weeks", "No systematic model monitoring"],
                        "impact_category": "risk", "estimated_savings": 100000, "estimated_revenue": 0, "timeline_estimate": "medium",
                        "status": "completed", "scored": True, "overall_score": 56.0,
                    },
                ],
            },
            {
                "name": "Security",
                "use_cases": [
                    {
                        "title": "Threat Detection and Response",
                        "description": "AI-powered security operations center that detects, correlates, and responds to cybersecurity threats in real-time.",
                        "goals": ["Reduce threat detection time to under 1 hour", "Automate response to common threats", "Achieve 99.9% threat coverage"],
                        "challenges": ["Evolving threat landscape", "Alert volume is overwhelming"],
                        "pain_points": ["Average threat detection time is 200 days", "Security team is understaffed"],
                        "impact_category": "risk", "estimated_savings": 300000, "estimated_revenue": 0, "timeline_estimate": "long",
                        "status": "completed", "scored": True, "overall_score": 52.0,
                    },
                ],
            },
        ],
    },
    {
        "name": "HealthFirst Medical Group",
        "description": "Multi-specialty medical practice network",
        "departments": [
            {
                "name": "HR / L&D",
                "use_cases": [
                    {
                        "title": "Personalized Learning Platform",
                        "description": "Adaptive learning system that adjusts course content and pace based on individual learner performance and preferences.",
                        "goals": ["Reduce training completion time by 30%", "Improve knowledge retention scores", "Enable self-paced development"],
                        "challenges": ["Content needs AI adaptation", "Measuring training ROI is difficult"],
                        "pain_points": ["60% dropout rate in online training", "Training costs $500K/year with unclear ROI"],
                        "impact_category": "time", "estimated_savings": 100000, "estimated_revenue": 50000, "timeline_estimate": "medium",
                        "status": "completed", "scored": True, "overall_score": 50.0,
                    },
                ],
            },
            {
                "name": "Operations",
                "use_cases": [
                    {
                        "title": "Clinical Documentation Automation",
                        "description": "NLP system to auto-generate clinical notes from doctor-patient conversations, reducing administrative burden on physicians.",
                        "goals": ["Reduce documentation time by 50%", "Improve note accuracy and completeness", "Free up 15+ hours per physician per week"],
                        "challenges": ["HIPAA compliance requirements", "Medical terminology complexity"],
                        "pain_points": ["Physicians spend 2 hours on documentation per patient", "Burnout rates at 40% in the organization"],
                        "impact_category": "time", "estimated_savings": 600000, "estimated_revenue": 200000, "timeline_estimate": "medium",
                        "status": "completed", "scored": True, "overall_score": 55.0,
                    },
                ],
            },
            {
                "name": "Compliance",
                "use_cases": [
                    {
                        "title": "HIPAA Compliance Monitoring",
                        "description": "AI system to continuously monitor compliance with HIPAA regulations, track violations, and generate compliance reports.",
                        "goals": ["Achieve 100% HIPAA compliance tracking", "Reduce compliance audit time by 50%", "Automate violation reporting"],
                        "challenges": ["Regulatory changes are frequent", "Multi-system data access"],
                        "pain_points": ["Compliance audits take 8+ weeks", "Manual compliance tracking misses 30% of violations"],
                        "impact_category": "risk", "estimated_savings": 200000, "estimated_revenue": 0, "timeline_estimate": "medium",
                        "status": "completed", "scored": True, "overall_score": 52.0,
                    },
                ],
            },
            {
                "name": "Patient Care",
                "use_cases": [
                    {
                        "title": "Virtual Nursing Assistant",
                        "description": "AI-powered virtual nursing assistant that provides 24/7 patient support, triage, and health monitoring guidance.",
                        "goals": ["Provide 24/7 patient support coverage", "Reduce nurse call volume by 40%", "Improve patient satisfaction scores"],
                        "challenges": ["Clinical accuracy requirements", "Patient trust in AI"],
                        "pain_points": ["Nurse burnout at 40%", "Patient satisfaction scores declining"],
                        "impact_category": "time", "estimated_savings": 300000, "estimated_revenue": 150000, "timeline_estimate": "long",
                        "status": "completed", "scored": True, "overall_score": 56.0,
                    },
                ],
            },
            {
                "name": "Revenue Cycle",
                "use_cases": [
                    {
                        "title": "Claim Denial Prevention",
                        "description": "AI system that predicts claim denials before submission and automatically corrects common denial triggers.",
                        "goals": ["Reduce claim denial rate to under 5%", "Automate claim corrections", "Improve first-pass yield to 95%"],
                        "challenges": [" payer-specific rules", "Complex billing codes"],
                        "pain_points": ["30% claim denial rate", "Revenue cycle takes 45+ days"],
                        "impact_category": "revenue", "estimated_savings": 0, "estimated_revenue": 800000, "timeline_estimate": "medium",
                        "status": "completed", "scored": True, "overall_score": 54.0,
                    },
                ],
            },
            {
                "name": "Supply Chain",
                "use_cases": [
                    {
                        "title": "Medical Supply Demand Forecasting",
                        "description": "AI system to predict medical supply needs across facilities, preventing shortages and reducing excess inventory.",
                        "goals": ["Eliminate supply shortages", "Reduce excess inventory by 30%", "Automate reorder triggers"],
                        "challenges": ["Variable demand patterns", "Multiple supplier sources"],
                        "pain_points": ["Supply shortages cause $200K+ in lost procedures quarterly", "Excess inventory ties up $1M+ in capital"],
                        "impact_category": "cost", "estimated_savings": 400000, "estimated_revenue": 0, "timeline_estimate": "medium",
                        "status": "completed", "scored": True, "overall_score": 52.0,
                    },
                ],
            },
            {
                "name": "Telemedicine",
                "use_cases": [
                    {
                        "title": "Remote Patient Monitoring",
                        "description": "AI-powered remote patient monitoring system that tracks patient vitals, alerts on anomalies, and enables virtual consultations.",
                        "goals": ["Monitor 1000+ patients remotely", "Reduce hospital readmissions by 25%", "Enable virtual triage"],
                        "challenges": ["Device interoperability", "Data privacy requirements"],
                        "pain_points": ["Hospital readmissions cost $1M+ annually", "In-person visits overwhelm clinic capacity"],
                        "impact_category": "revenue", "estimated_savings": 200000, "estimated_revenue": 300000, "timeline_estimate": "long",
                        "status": "completed", "scored": True, "overall_score": 58.0,
                    },
                ],
            },
            {
                "name": "Finance",
                "use_cases": [
                    {
                        "title": "Healthcare Cost Optimization",
                        "description": "AI analysis of healthcare spending across facilities to identify cost optimization opportunities and reduce waste.",
                        "goals": ["Reduce operational costs by 10%", "Identify billing discrepancies", "Optimize resource allocation"],
                        "challenges": ["Complex cost allocation", "Regulatory constraints on cost cuts"],
                        "pain_points": ["Unexplained cost variance of $2M+ annually", "No proactive cost monitoring"],
                        "impact_category": "cost", "estimated_savings": 500000, "estimated_revenue": 0, "timeline_estimate": "medium",
                        "status": "completed", "scored": True, "overall_score": 50.0,
                    },
                ],
            },
            {
                "name": "IT",
                "use_cases": [
                    {
                        "title": "EHR System Optimization",
                        "description": "AI analysis of electronic health record usage patterns to optimize workflows, reduce physician clicks, and improve adoption.",
                        "goals": ["Reduce physician EHR time by 30%", "Improve EHR adoption rates", "Optimize clinical workflows"],
                        "challenges": ["Physician workflow diversity", "EHR vendor limitations"],
                        "pain_points": ["Physicians spend 30% time in EHR", "EHR-related burnout is widespread"],
                        "impact_category": "efficiency", "estimated_savings": 300000, "estimated_revenue": 0, "timeline_estimate": "medium",
                        "status": "completed", "scored": True, "overall_score": 55.0,
                    },
                ],
            },
            {
                "name": "Patient Relations",
                "use_cases": [
                    {
                        "title": "Patient Satisfaction Analytics",
                        "description": "AI analysis of patient feedback, survey data, and interactions to identify satisfaction drivers and improve experience.",
                        "goals": ["Improve patient satisfaction scores by 15%", "Identify satisfaction drivers", "Enable proactive improvement"],
                        "challenges": ["Survey response bias", "Multi-channel feedback aggregation"],
                        "pain_points": ["Patient satisfaction scores below industry average", "Slow feedback loop"],
                        "impact_category": "revenue", "estimated_savings": 0, "estimated_revenue": 200000, "timeline_estimate": "short",
                        "status": "completed", "scored": True, "overall_score": 52.0,
                    },
                ],
            },
            {
                "name": "Research",
                "use_cases": [
                    {
                        "title": "Clinical Trial Patient Matching",
                        "description": "AI system to match patients with suitable clinical trials based on medical history, demographics, and condition data.",
                        "goals": ["Reduce patient matching time by 80%", "Increase trial enrollment by 50%", "Improve trial diversity"],
                        "challenges": ["Patient privacy requirements", "Complex trial criteria"],
                        "pain_points": ["Trial recruitment takes 6+ months", "70% of trials are under-enrolled"],
                        "impact_category": "revenue", "estimated_savings": 100000, "estimated_revenue": 400000, "timeline_estimate": "long",
                        "status": "completed", "scored": True, "overall_score": 50.0,
                    },
                ],
            },
            {
                "name": "Quality",
                "use_cases": [
                    {
                        "title": "Medical Error Prevention",
                        "description": "AI system to analyze clinical workflows and identify opportunities to reduce medical errors and improve patient safety.",
                        "goals": ["Reduce medical errors by 50%", "Identify high-risk workflows", "Improve patient safety culture"],
                        "challenges": ["Clinical data complexity", "System integration challenges"],
                        "pain_points": ["Medical errors cause 100+ deaths annually", "Error tracking is manual and reactive"],
                        "impact_category": "risk", "estimated_savings": 500000, "estimated_revenue": 0, "timeline_estimate": "long",
                        "status": "completed", "scored": True, "overall_score": 54.0,
                    },
                ],
            },
        ],
    },
    {
        "name": "RetailMax",
        "description": "National retail chain with 200+ stores",
        "departments": [
            {
                "name": "Operations",
                "use_cases": [
                    {
                        "title": "Inventory Optimization with AI Forecasting",
                        "description": "AI-driven inventory management system that predicts demand at store level, automatically adjusts reorder points, and minimizes stockouts while reducing excess inventory.",
                        "goals": ["Reduce stockouts by 50%", "Cut excess inventory by 25%", "Increase inventory turnover ratio by 20%"],
                        "challenges": ["Seasonal demand patterns vary by region", "Integration with legacy POS systems"],
                        "pain_points": ["20% stockout rate on high-demand items", "$2M+ in excess inventory costs annually"],
                        "impact_category": "cost", "estimated_savings": 800000, "estimated_revenue": 300000, "timeline_estimate": "medium",
                        "status": "completed", "scored": True, "overall_score": 55.0,
                    },
                    {
                        "title": "Smart Store Layout Optimization",
                        "description": "Computer vision and foot traffic analysis to optimize store layouts for maximum sales conversion and customer satisfaction.",
                        "goals": ["Increase average dwell time by 15%", "Improve conversion rate by 10%", "Optimize product placement based on heat maps"],
                        "challenges": ["Privacy regulations around camera data", "Varying store layouts across locations"],
                        "pain_points": ["30% of high-margin products in low-visibility areas", "Store managers guess at optimal layouts"],
                        "impact_category": "revenue", "estimated_savings": 50000, "estimated_revenue": 400000, "timeline_estimate": "long",
                        "status": "completed", "scored": True, "overall_score": 50.0,
                    },
                ],
            },
            {
                "name": "Customer Success",
                "use_cases": [
                    {
                        "title": "Personalized Shopping Experience",
                        "description": "AI-powered recommendation engine for both in-store and online shopping, increasing customer lifetime value through personalized product suggestions.",
                        "goals": ["Increase average order value by 20%", "Improve customer retention by 15%", "Achieve 40% of revenue from personalized recommendations"],
                        "challenges": ["Cold start problem for new customers", "Integrating online and in-store data"],
                        "pain_points": ["Generic promotions have 2% conversion rate", "No visibility into cross-channel shopping behavior"],
                        "impact_category": "revenue", "estimated_savings": 0, "estimated_revenue": 600000, "timeline_estimate": "medium",
                        "status": "completed", "scored": True, "overall_score": 54.0,
                    },
                ],
            },
            {
                "name": "Merchandising",
                "use_cases": [
                    {
                        "title": "Store-Level Demand Forecasting",
                        "description": "ML model to forecast demand at individual store level considering local demographics, events, and weather patterns.",
                        "goals": ["Improve store-level forecast accuracy to 85%", "Reduce manual forecasting workload by 70%", "Support automated replenishment"],
                        "challenges": ["Store-level data granularity", "External factor modeling"],
                        "pain_points": ["Centralized forecasting misses local trends", "Merchandising team spends 10 hours/week on forecasting"],
                        "impact_category": "efficiency", "estimated_savings": 300000, "estimated_revenue": 150000, "timeline_estimate": "medium",
                        "status": "completed", "scored": True, "overall_score": 52.0,
                    },
                ],
            },
            {
                "name": "Supply Chain",
                "use_cases": [
                    {
                        "title": "Last Mile Delivery Route Optimization",
                        "description": "AI system to optimize last-mile delivery routes considering traffic, weather, and delivery windows for maximum efficiency.",
                        "goals": ["Reduce delivery costs by 20%", "Improve on-time delivery to 98%", "Optimize driver utilization"],
                        "challenges": ["Dynamic traffic conditions", "Customer time window constraints"],
                        "pain_points": ["Delivery costs represent 15% of online revenue", "On-time delivery is only 85%"],
                        "impact_category": "cost", "estimated_savings": 400000, "estimated_revenue": 0, "timeline_estimate": "short",
                        "status": "completed", "scored": True, "overall_score": 56.0,
                    },
                ],
            },
            {
                "name": "Marketing",
                "use_cases": [
                    {
                        "title": "Customer Segmentation and Targeting",
                        "description": "AI-powered customer segmentation to create precise target audiences for marketing campaigns based on behavior and purchase history.",
                        "goals": ["Increase campaign ROI by 30%", "Reduce customer acquisition cost by 20%", "Improve customer lifetime value"],
                        "challenges": ["Data quality across channels", "Privacy regulations"],
                        "pain_points": ["Marketing campaigns have 1% conversion rate", "One-size-fits-all messaging"],
                        "impact_category": "revenue", "estimated_savings": 0, "estimated_revenue": 500000, "timeline_estimate": "medium",
                        "status": "completed", "scored": True, "overall_score": 54.0,
                    },
                ],
            },
            {
                "name": "HR / L&D",
                "use_cases": [
                    {
                        "title": "Retail Staff Scheduling Optimization",
                        "description": "AI system to create optimal staff schedules based on foot traffic, sales forecasts, and labor compliance requirements.",
                        "goals": ["Reduce labor costs by 10%", "Improve staff coverage during peak hours", "Ensure labor law compliance"],
                        "challenges": ["Variable foot traffic patterns", "Employee availability preferences"],
                        "pain_points": ["Overstaffing during slow periods costs $500K annually", "Understaffing during peaks drives customers away"],
                        "impact_category": "cost", "estimated_savings": 300000, "estimated_revenue": 0, "timeline_estimate": "short",
                        "status": "completed", "scored": True, "overall_score": 58.0,
                    },
                ],
            },
            {
                "name": "Finance",
                "use_cases": [
                    {
                        "title": "Retail Pricing Optimization",
                        "description": "AI system to optimize pricing across product categories based on demand elasticity, competitor pricing, and inventory levels.",
                        "goals": ["Increase gross margin by 5%", "Reduce markdown events by 30%", "Automate competitive price matching"],
                        "challenges": ["Price elasticity varies by product", "Competitor price scraping is noisy"],
                        "pain_points": ["Excessive markdowns cost $1M+ annually", "Manual price adjustments are slow"],
                        "impact_category": "revenue", "estimated_savings": 200000, "estimated_revenue": 400000, "timeline_estimate": "medium",
                        "status": "completed", "scored": True, "overall_score": 56.0,
                    },
                ],
            },
            {
                "name": "IT",
                "use_cases": [
                    {
                        "title": "POS System Reliability Monitoring",
                        "description": "AI monitoring of POS systems across all retail locations to predict failures and ensure uninterrupted checkout operations.",
                        "goals": ["Reduce POS downtime by 90%", "Predict hardware failures before they occur", "Automate IT dispatch"],
                        "challenges": ["200+ locations with varying hardware", "Network connectivity issues"],
                        "pain_points": ["POS downtime costs $10K+ per hour per store", "IT team cannot monitor all locations"],
                        "impact_category": "efficiency", "estimated_savings": 150000, "estimated_revenue": 0, "timeline_estimate": "short",
                        "status": "completed", "scored": True, "overall_score": 55.0,
                    },
                ],
            },
            {
                "name": "Loss Prevention",
                "use_cases": [
                    {
                        "title": "Shoplifting Detection and Prevention",
                        "description": "AI-powered video analytics to detect shoplifting behavior in real-time and alert security staff.",
                        "goals": ["Reduce shoplifting losses by 40%", "Reduce false alarms by 60%", "Automate incident documentation"],
                        "challenges": ["Privacy regulations", "False positive management"],
                        "pain_points": ["Annual shoplifting losses of $2M+", "Security staff cannot monitor all cameras"],
                        "impact_category": "risk", "estimated_savings": 400000, "estimated_revenue": 0, "timeline_estimate": "medium",
                        "status": "completed", "scored": True, "overall_score": 52.0,
                    },
                ],
            },
            {
                "name": "Customer Analytics",
                "use_cases": [
                    {
                        "title": "Loyalty Program Optimization",
                        "description": "AI analysis of loyalty program data to optimize rewards, personalize offers, and increase member engagement.",
                        "goals": ["Increase loyalty program engagement by 25%", "Improve redemption rate to 60%", "Boost member lifetime value by 15%"],
                        "challenges": ["Diverse member segments", "Reward cost control"],
                        "pain_points": ["Only 20% of members are actively engaged", "Generic rewards have low appeal"],
                        "impact_category": "revenue", "estimated_savings": 0, "estimated_revenue": 350000, "timeline_estimate": "medium",
                        "status": "completed", "scored": True, "overall_score": 54.0,
                    },
                ],
            },
            {
                "name": "Real Estate",
                "use_cases": [
                    {
                        "title": "New Store Location Scoring",
                        "description": "AI system to score potential new store locations based on demographics, competition, foot traffic, and accessibility.",
                        "goals": ["Improve new store success rate by 30%", "Reduce site selection time by 50%", "Data-driven site decisions"],
                        "challenges": ["Data availability varies by market", "Long-term trend forecasting"],
                        "pain_points": ["25% of new stores underperform", "Site selection is subjective and slow"],
                        "impact_category": "revenue", "estimated_savings": 0, "estimated_revenue": 600000, "timeline_estimate": "long",
                        "status": "completed", "scored": True, "overall_score": 50.0,
                    },
                ],
            },
            {
                "name": "Sustainability",
                "use_cases": [
                    {
                        "title": "Retail Waste Reduction",
                        "description": "AI system to analyze and reduce waste across retail operations including packaging, food waste, and unsold inventory.",
                        "goals": ["Reduce waste by 25%", "Improve sustainability reporting", "Identify waste hotspots"],
                        "challenges": ["Multi-category waste tracking", "Supplier cooperation"],
                        "pain_points": ["Waste costs $500K+ annually", "No systematic waste tracking"],
                        "impact_category": "cost", "estimated_savings": 200000, "estimated_revenue": 0, "timeline_estimate": "medium",
                        "status": "completed", "scored": True, "overall_score": 48.0,
                    },
                ],
            },
        ],
    },
]

# Scoring data for all use cases (including previously unscored ones)
SCORING_DATA = {
    # ── Manufacturing (already scored) ──
    "Predictive Maintenance for Manufacturing Equipment": {
        "scores": {"data_readiness": 80, "technical_feasibility": 75, "organizational_readiness": 65, "roi_potential": 85, "risk_compliance": 60, "implementation_complexity": 70},
        "reasoning": "High data readiness from sensor infrastructure. Strong ROI with clear cost reduction.",
        "recommendations": ["Build data pipeline for sensor data aggregation", "Pilot on single production line before scale", "Develop maintenance team training program"],
    },
    "AI-Driven Design Optimization": {
        "scores": {"data_readiness": 60, "technical_feasibility": 65, "organizational_readiness": 55, "roi_potential": 70, "risk_compliance": 50, "implementation_complexity": 62},
        "reasoning": "Design optimization has strong ROI but needs domain-specific training data and CAD integration.",
        "recommendations": ["Build CAD-integrated AI pipeline", "Start with single product category", "Establish design review governance"],
    },
    "Quality Analytics Dashboard": {
        "scores": {"data_readiness": 70, "technical_feasibility": 68, "organizational_readiness": 62, "roi_potential": 72, "risk_compliance": 68, "implementation_complexity": 65},
        "reasoning": "Quality analytics has strong technical feasibility with available dashboard tools.",
        "recommendations": ["Start with single product line", "Invest in image data collection", "Develop defect taxonomy with quality team"],
    },
    "Automated Defect Classification": {
        "scores": {"data_readiness": 65, "technical_feasibility": 68, "organizational_readiness": 60, "roi_potential": 70, "risk_compliance": 62, "implementation_complexity": 58},
        "reasoning": "Computer vision for defect classification is mature technology with clear ROI.",
        "recommendations": ["Deploy on high-volume production line first", "Build labeled defect dataset", "Integrate with existing QA workflow"],
    },
    "Cost Optimization Analytics": {
        "scores": {"data_readiness": 62, "technical_feasibility": 60, "organizational_readiness": 58, "roi_potential": 72, "risk_compliance": 55, "implementation_complexity": 52},
        "reasoning": "Cost optimization has strong ROI potential but requires cross-departmental data integration.",
        "recommendations": ["Start with procurement and operations", "Build centralized cost data warehouse", "Establish cost accountability framework"],
    },
    "Demand Forecasting for Supply Chain": {
        "scores": {"data_readiness": 50, "technical_feasibility": 55, "organizational_readiness": 48, "roi_potential": 60, "risk_compliance": 52, "implementation_complexity": 55},
        "reasoning": "Demand forecasting has good ROI but data quality and seasonal complexity are blockers.",
        "recommendations": ["Clean and standardize historical data", "Start with top 20% of products", "Build external factor integration layer"],
    },
    "Vendor Risk Analytics": {
        "scores": {"data_readiness": 54, "technical_feasibility": 58, "organizational_readiness": 52, "roi_potential": 62, "risk_compliance": 58, "implementation_complexity": 55},
        "reasoning": "Vendor risk scoring is valuable but limited by vendor data availability and model calibration needs.",
        "recommendations": ["Build vendor risk data pipeline", "Start with critical tier-1 suppliers", "Establish risk threshold alerts"],
    },
    "Intelligent Sourcing Recommendations": {
        "scores": {"data_readiness": 56, "technical_feasibility": 60, "organizational_readiness": 54, "roi_potential": 64, "risk_compliance": 55, "implementation_complexity": 55},
        "reasoning": "Sourcing recommendations have strong ROI but supplier data quality and multi-criteria complexity are challenges.",
        "recommendations": ["Standardize supplier data collection", "Build multi-criteria optimization engine", "Implement supplier scorecard"],
    },
    "AI Production Schedule Optimizer": {
        "scores": {"data_readiness": 52, "technical_feasibility": 55, "organizational_readiness": 50, "roi_potential": 58, "risk_compliance": 54, "implementation_complexity": 58},
        "reasoning": "Production scheduling optimization has clear ROI but dynamic constraints make it challenging.",
        "recommendations": ["Start with single production line", "Build constraint optimization model", "Implement schedule change management"],
    },
    "Workplace Safety Monitoring": {
        "scores": {"data_readiness": 58, "technical_feasibility": 62, "organizational_readiness": 55, "roi_potential": 65, "risk_compliance": 60, "implementation_complexity": 55},
        "reasoning": "Safety monitoring has strong ROI potential and regulatory motivation but IoT coverage gaps exist.",
        "recommendations": ["Deploy sensors in high-risk areas", "Integrate with safety management system", "Build hazard prediction model"],
    },
    "Workforce Skills Analytics": {
        "scores": {"data_readiness": 50, "technical_feasibility": 54, "organizational_readiness": 52, "roi_potential": 58, "risk_compliance": 50, "implementation_complexity": 48},
        "reasoning": "Skills analytics has good ROI but requires systematic skills data capture and change management.",
        "recommendations": ["Build skills taxonomy", "Implement skills assessment survey", "Integrate with training platform"],
    },
    "Manufacturing IT Infrastructure Monitoring": {
        "scores": {"data_readiness": 58, "technical_feasibility": 60, "organizational_readiness": 55, "roi_potential": 58, "risk_compliance": 56, "implementation_complexity": 52},
        "reasoning": "IT infrastructure monitoring has clear ROI from downtime reduction but legacy systems complicate integration.",
        "recommendations": ["Deploy monitoring agents at key sites", "Build centralized dashboard", "Implement anomaly detection baseline"],
    },
    "B2B Customer Satisfaction Analytics": {
        "scores": {"data_readiness": 54, "technical_feasibility": 58, "organizational_readiness": 52, "roi_potential": 60, "risk_compliance": 55, "implementation_complexity": 55},
        "reasoning": "B2B satisfaction analytics has strong revenue impact but feedback data is sparse and multi-stakeholder.",
        "recommendations": ["Implement structured feedback collection", "Build customer health score", "Integrate with CRM"],
    },
    "Energy Consumption Optimization": {
        "scores": {"data_readiness": 52, "technical_feasibility": 55, "organizational_readiness": 50, "roi_potential": 58, "risk_compliance": 54, "implementation_complexity": 56},
        "reasoning": "Energy optimization has clear cost and sustainability benefits but production constraints limit flexibility.",
        "recommendations": ["Deploy sub-metering at equipment level", "Build energy baseline", "Implement peak demand optimization"],
    },
    # ── Financial Services ──
    "Fraud Detection for Financial Transactions": {
        "scores": {"data_readiness": 75, "technical_feasibility": 65, "organizational_readiness": 70, "roi_potential": 80, "risk_compliance": 55, "implementation_complexity": 58},
        "reasoning": "Strong ROI from fraud reduction with good existing transaction data. Regulatory compliance is the biggest risk factor.",
        "recommendations": ["Implement in parallel with existing rules-based system", "Develop explainability framework for regulators", "Establish fraud detection governance board"],
    },
    "Automated Customer Support Triage": {
        "scores": {"data_readiness": 72, "technical_feasibility": 78, "organizational_readiness": 68, "roi_potential": 65, "risk_compliance": 72, "implementation_complexity": 70},
        "reasoning": "Technical feasibility is high. Strong potential to improve customer satisfaction and reduce costs.",
        "recommendations": ["Begin with English language support only", "Create escalation protocols for complex cases", "Track first-contact resolution rate as KPI"],
    },
    "AI-Powered Credit Risk Assessment": {
        "scores": {"data_readiness": 44, "technical_feasibility": 50, "organizational_readiness": 42, "roi_potential": 55, "risk_compliance": 30, "implementation_complexity": 38},
        "reasoning": "Credit risk has high regulatory burden. Model interpretability is critical. Data quality varies.",
        "recommendations": ["Start with commercial lending before consumer", "Implement model interpretability tools", "Build comprehensive testing framework"],
    },
    "Churn Prediction and Retention": {
        "scores": {"data_readiness": 36, "technical_feasibility": 42, "organizational_readiness": 38, "roi_potential": 50, "risk_compliance": 45, "implementation_complexity": 32},
        "reasoning": "Limited historical churn data makes training challenging. High churn rate presents strong opportunity.",
        "recommendations": ["Start by building data collection infrastructure", "Use rule-based heuristics as interim solution", "Partner with analytics team"],
    },
    "Automated Regulatory Reporting": {
        "scores": {"data_readiness": 50, "technical_feasibility": 55, "organizational_readiness": 52, "roi_potential": 58, "risk_compliance": 55, "implementation_complexity": 50},
        "reasoning": "Regulatory reporting automation has strong efficiency gains but requirements change frequently.",
        "recommendations": ["Build modular report templates", "Implement change tracking for regulations", "Start with highest-volume reports"],
    },
    "AML Transaction Monitoring": {
        "scores": {"data_readiness": 58, "technical_feasibility": 62, "organizational_readiness": 55, "roi_potential": 65, "risk_compliance": 60, "implementation_complexity": 55},
        "reasoning": "AML monitoring has high ROI from false positive reduction but evolving techniques require continuous updates.",
        "recommendations": ["Implement graph-based transaction analysis", "Build analyst feedback loop", "Integrate with existing AML system"],
    },
    "Financial Statement Fraud Detection": {
        "scores": {"data_readiness": 53, "technical_feasibility": 56, "organizational_readiness": 50, "roi_potential": 60, "risk_compliance": 55, "implementation_complexity": 54},
        "reasoning": "Financial statement analysis has clear credit risk value but diverse accounting standards complicate modeling.",
        "recommendations": ["Start with domestic GAAP data", "Build ratio analysis engine", "Implement anomaly scoring"],
    },
    "Core Banking System Anomaly Detection": {
        "scores": {"data_readiness": 55, "technical_feasibility": 58, "organizational_readiness": 52, "roi_potential": 58, "risk_compliance": 55, "implementation_complexity": 55},
        "reasoning": "Core banking monitoring has clear ROI but legacy system integration and high-volume processing are challenges.",
        "recommendations": ["Deploy on non-production systems first", "Build transaction pattern baseline", "Implement alerting workflow"],
    },
    "Market Sentiment Analysis": {
        "scores": {"data_readiness": 50, "technical_feasibility": 54, "organizational_readiness": 48, "roi_potential": 55, "risk_compliance": 50, "implementation_complexity": 50},
        "reasoning": "Market sentiment has strategic value for investor relations but data is noisy and noisy.",
        "recommendations": ["Start with financial news sources", "Build sentiment trend dashboard", "Integrate with earnings calendar"],
    },
    "Model Risk Validation": {
        "scores": {"data_readiness": 52, "technical_feasibility": 55, "organizational_readiness": 50, "roi_potential": 58, "risk_compliance": 60, "implementation_complexity": 50},
        "reasoning": "Model risk validation is critical for regulatory compliance but complex architectures limit automation.",
        "recommendations": ["Start with highest-risk model categories", "Build automated testing framework", "Implement model inventory tracking"],
    },
    "Algorithmic Trading Strategy Discovery": {
        "scores": {"data_readiness": 55, "technical_feasibility": 60, "organizational_readiness": 52, "roi_potential": 65, "risk_compliance": 48, "implementation_complexity": 55},
        "reasoning": "Trading strategy discovery has enormous revenue potential but market noise and overfitting are major risks.",
        "recommendations": ["Start with established factor models", "Implement strict out-of-sample testing", "Build strategy portfolio diversification"],
    },
    "Portfolio Optimization Engine": {
        "scores": {"data_readiness": 54, "technical_feasibility": 58, "organizational_readiness": 52, "roi_potential": 62, "risk_compliance": 50, "implementation_complexity": 54},
        "reasoning": "Portfolio optimization has strong revenue potential but regulatory constraints and client complexity are barriers.",
        "recommendations": ["Build multi-objective optimization engine", "Implement client risk profiling", "Integrate with existing wealth tools"],
    },
    "Banking Customer Churn Prediction": {
        "scores": {"data_readiness": 52, "technical_feasibility": 55, "organizational_readiness": 50, "roi_potential": 58, "risk_compliance": 52, "implementation_complexity": 50},
        "reasoning": "Churn prediction has strong revenue value but multi-channel behavioral data is complex to integrate.",
        "recommendations": ["Build unified customer view", "Implement behavioral scoring", "Design targeted retention campaigns"],
    },
    "Financial Services Workforce Analytics": {
        "scores": {"data_readiness": 50, "technical_feasibility": 54, "organizational_readiness": 48, "roi_potential": 55, "risk_compliance": 50, "implementation_complexity": 48},
        "reasoning": "Workforce analytics has operational value but specialized finance skills and competitive market complicate planning.",
        "recommendations": ["Build skills inventory", "Implement attrition prediction", "Integrate with HR systems"],
    },
    "Branch Network Optimization": {
        "scores": {"data_readiness": 48, "technical_feasibility": 52, "organizational_readiness": 45, "roi_potential": 55, "risk_compliance": 50, "implementation_complexity": 52},
        "reasoning": "Branch optimization has clear cost savings potential but real estate and community constraints limit flexibility.",
        "recommendations": ["Build branch performance scorecard", "Analyze foot traffic and demographics", "Pilot with lowest-performing branches"],
    },
    # ── Healthcare ──
    "Personalized Learning Platform": {
        "scores": {"data_readiness": 50, "technical_feasibility": 54, "organizational_readiness": 52, "roi_potential": 58, "risk_compliance": 50, "implementation_complexity": 50},
        "reasoning": "Training personalization has clear ROI but content adaptation and change management are challenges.",
        "recommendations": ["Build adaptive learning engine", "Create content taxonomies", "Implement learning analytics"],
    },
    "Clinical Documentation Automation": {
        "scores": {"data_readiness": 55, "technical_feasibility": 60, "organizational_readiness": 52, "roi_potential": 65, "risk_compliance": 55, "implementation_complexity": 55},
        "reasoning": "Clinical documentation has strong time-saving potential but HIPAA compliance and physician trust are barriers.",
        "recommendations": ["Implement HIPAA-compliant NLP pipeline", "Start with single specialty", "Build physician review workflow"],
    },
    "HIPAA Compliance Monitoring": {
        "scores": {"data_readiness": 52, "technical_feasibility": 55, "organizational_readiness": 50, "roi_potential": 58, "risk_compliance": 62, "implementation_complexity": 50},
        "reasoning": "HIPAA monitoring has high regulatory value but frequent changes and multi-system complexity limit automation.",
        "recommendations": ["Build compliance rule engine", "Implement continuous monitoring", "Integrate with audit systems"],
    },
    "Virtual Nursing Assistant": {
        "scores": {"data_readiness": 56, "technical_feasibility": 62, "organizational_readiness": 55, "roi_potential": 65, "risk_compliance": 52, "implementation_complexity": 58},
        "reasoning": "Virtual nursing has strong clinical value but accuracy requirements and patient trust are significant barriers.",
        "recommendations": ["Start with low-risk patient populations", "Implement clinician oversight", "Build escalation pathways"],
    },
    "Claim Denial Prevention": {
        "scores": {"data_readiness": 54, "technical_feasibility": 58, "organizational_readiness": 52, "roi_potential": 62, "risk_compliance": 55, "implementation_complexity": 54},
        "reasoning": "Claim denial prevention has strong revenue impact but payer-specific rules and billing complexity are challenges.",
        "recommendations": ["Build payer rule knowledge base", "Implement pre-submission validation", "Track denial root causes"],
    },
    "Medical Supply Demand Forecasting": {
        "scores": {"data_readiness": 52, "technical_feasibility": 55, "organizational_readiness": 50, "roi_potential": 58, "risk_compliance": 55, "implementation_complexity": 52},
        "reasoning": "Supply forecasting has clear cost savings but variable demand and multi-supplier complexity exist.",
        "recommendations": ["Build consumption prediction model", "Implement automated reorder triggers", "Integrate with inventory system"],
    },
    "Remote Patient Monitoring": {
        "scores": {"data_readiness": 58, "technical_feasibility": 62, "organizational_readiness": 55, "roi_potential": 65, "risk_compliance": 52, "implementation_complexity": 58},
        "reasoning": "Remote monitoring has strong revenue and cost benefits but device interoperability and privacy are barriers.",
        "recommendations": ["Standardize device protocols", "Implement anomaly alerting", "Build virtual care workflows"],
    },
    "Healthcare Cost Optimization": {
        "scores": {"data_readiness": 50, "technical_feasibility": 54, "organizational_readiness": 48, "roi_potential": 58, "risk_compliance": 50, "implementation_complexity": 50},
        "reasoning": "Cost optimization has strong ROI but complex allocation and regulatory constraints limit approaches.",
        "recommendations": ["Build cost transparency dashboard", "Implement variance tracking", "Create accountability framework"],
    },
    "EHR System Optimization": {
        "scores": {"data_readiness": 55, "technical_feasibility": 58, "organizational_readiness": 52, "roi_potential": 58, "risk_compliance": 55, "implementation_complexity": 55},
        "reasoning": "EHR optimization has strong physician satisfaction and efficiency impact but workflow diversity is a challenge.",
        "recommendations": ["Conduct physician workflow analysis", "Implement EHR usage analytics", "Build custom workflow templates"],
    },
    "Patient Satisfaction Analytics": {
        "scores": {"data_readiness": 52, "technical_feasibility": 55, "organizational_readiness": 50, "roi_potential": 58, "risk_compliance": 52, "implementation_complexity": 50},
        "reasoning": "Patient satisfaction analytics has direct revenue impact but survey bias and slow feedback loops exist.",
        "recommendations": ["Implement multi-channel feedback", "Build real-time satisfaction tracking", "Create improvement action plans"],
    },
    "Clinical Trial Patient Matching": {
        "scores": {"data_readiness": 50, "technical_feasibility": 54, "organizational_readiness": 48, "roi_potential": 55, "risk_compliance": 45, "implementation_complexity": 56},
        "reasoning": "Trial matching has research value but privacy requirements and complex criteria limit scope.",
        "recommendations": ["Build patient eligibility engine", "Implement data anonymization", "Partner with research networks"],
    },
    "Medical Error Prevention": {
        "scores": {"data_readiness": 54, "technical_feasibility": 58, "organizational_readiness": 52, "roi_potential": 62, "risk_compliance": 58, "implementation_complexity": 54},
        "reasoning": "Medical error prevention has critical patient safety impact but clinical data complexity is a major challenge.",
        "recommendations": ["Start with high-error workflow areas", "Build error pattern detection", "Implement incident reporting integration"],
    },
    # ── Retail ──
    "Inventory Optimization with AI Forecasting": {
        "scores": {"data_readiness": 55, "technical_feasibility": 58, "organizational_readiness": 52, "roi_potential": 65, "risk_compliance": 55, "implementation_complexity": 55},
        "reasoning": "Inventory optimization has strong ROI from stockout reduction and excess inventory management.",
        "recommendations": ["Implement store-level demand model", "Build automated reorder system", "Integrate with existing ERP"],
    },
    "Smart Store Layout Optimization": {
        "scores": {"data_readiness": 50, "technical_feasibility": 55, "organizational_readiness": 48, "roi_potential": 58, "risk_compliance": 45, "implementation_complexity": 55},
        "reasoning": "Store layout optimization has revenue impact but privacy regulations and varying layouts complicate implementation.",
        "recommendations": ["Start with pilot store locations", "Build foot traffic heat maps", "Integrate with sales data"],
    },
    "Personalized Shopping Experience": {
        "scores": {"data_readiness": 54, "technical_feasibility": 58, "organizational_readiness": 52, "roi_potential": 62, "risk_compliance": 55, "implementation_complexity": 54},
        "reasoning": "Personalization has strong revenue potential but cold start and multi-channel data integration are challenges.",
        "recommendations": ["Build unified customer profile", "Implement collaborative filtering", "Test personalization incrementally"],
    },
    "Customer Satisfaction Analytics": {
        "scores": {"data_readiness": 52, "technical_feasibility": 55, "organizational_readiness": 50, "roi_potential": 58, "risk_compliance": 52, "implementation_complexity": 50},
        "reasoning": "Satisfaction analytics has direct revenue impact but survey bias and slow feedback loops exist.",
        "recommendations": ["Implement multi-channel feedback", "Build real-time satisfaction tracking", "Create improvement action plans"],
    },
    "Store-Level Demand Forecasting": {
        "scores": {"data_readiness": 52, "technical_feasibility": 55, "organizational_readiness": 50, "roi_potential": 58, "risk_compliance": 55, "implementation_complexity": 52},
        "reasoning": "Store-level forecasting has efficiency gains but data granularity and external factor modeling are challenges.",
        "recommendations": ["Build store-specific demand models", "Integrate local event data", "Implement automated forecasting"],
    },
    "Last Mile Delivery Route Optimization": {
        "scores": {"data_readiness": 56, "technical_feasibility": 60, "organizational_readiness": 55, "roi_potential": 62, "risk_compliance": 58, "implementation_complexity": 55},
        "reasoning": "Route optimization has clear cost savings but dynamic traffic and customer constraints complicate implementation.",
        "recommendations": ["Implement real-time route optimization", "Build traffic prediction model", "Integrate with delivery management system"],
    },
    "Customer Segmentation and Targeting": {
        "scores": {"data_readiness": 54, "technical_feasibility": 58, "organizational_readiness": 52, "roi_potential": 62, "risk_compliance": 55, "implementation_complexity": 54},
        "reasoning": "Customer segmentation has strong revenue impact but data quality and privacy regulations are concerns.",
        "recommendations": ["Build unified customer data platform", "Implement behavioral segmentation", "Test targeted campaigns"],
    },
    "Retail Pricing Optimization": {
        "scores": {"data_readiness": 56, "technical_feasibility": 60, "organizational_readiness": 55, "roi_potential": 65, "risk_compliance": 55, "implementation_complexity": 55},
        "reasoning": "Pricing optimization has direct margin impact but elasticity varies by product and competitor scraping is noisy.",
        "recommendations": ["Build price elasticity models", "Implement competitive price monitoring", "Test pricing changes incrementally"],
    },
    "POS System Reliability Monitoring": {
        "scores": {"data_readiness": 55, "technical_feasibility": 58, "organizational_readiness": 52, "roi_potential": 58, "risk_compliance": 55, "implementation_complexity": 52},
        "reasoning": "POS monitoring has clear ROI from downtime reduction but 200+ locations with varying hardware complicate deployment.",
        "recommendations": ["Deploy monitoring agents at key locations", "Build centralized POS dashboard", "Implement predictive maintenance"],
    },
    "Shoplifting Detection and Prevention": {
        "scores": {"data_readiness": 52, "technical_feasibility": 55, "organizational_readiness": 50, "roi_potential": 58, "risk_compliance": 55, "implementation_complexity": 52},
        "reasoning": "Loss prevention has direct cost savings but privacy regulations and false positive management are challenges.",
        "recommendations": ["Start with highest-loss locations", "Build video analytics pipeline", "Integrate with security operations"],
    },
    "Loyalty Program Optimization": {
        "scores": {"data_readiness": 54, "technical_feasibility": 58, "organizational_readiness": 52, "roi_potential": 62, "risk_compliance": 55, "implementation_complexity": 54},
        "reasoning": "Loyalty optimization has strong revenue potential but diverse member segments and reward cost control exist.",
        "recommendations": ["Build member segmentation engine", "Implement personalized rewards", "Track member lifetime value"],
    },
    "New Store Location Scoring": {
        "scores": {"data_readiness": 50, "technical_feasibility": 55, "organizational_readiness": 48, "roi_potential": 55, "risk_compliance": 50, "implementation_complexity": 54},
        "reasoning": "Site selection has major revenue impact but data availability varies and long-term forecasting is uncertain.",
        "recommendations": ["Build location scoring model", "Integrate demographic and traffic data", "Implement pilot store validation"],
    },
    "Retail Waste Reduction": {
        "scores": {"data_readiness": 48, "technical_feasibility": 52, "organizational_readiness": 45, "roi_potential": 55, "risk_compliance": 50, "implementation_complexity": 52},
        "reasoning": "Waste reduction has cost and sustainability benefits but multi-category tracking is complex.",
        "recommendations": ["Build waste tracking dashboard", "Implement inventory waste analysis", "Create supplier waste reduction program"],
    },
    "Supply Chain Route Optimization": {
        "scores": {"data_readiness": 56, "technical_feasibility": 60, "organizational_readiness": 55, "roi_potential": 62, "risk_compliance": 58, "implementation_complexity": 55},
        "reasoning": "Route optimization has clear cost savings but dynamic conditions and delivery constraints exist.",
        "recommendations": ["Implement dynamic routing engine", "Build traffic prediction model", "Integrate with fleet management system"],
    },
    "Social Listening and Brand Monitoring": {
        "scores": {"data_readiness": 54, "technical_feasibility": 58, "organizational_readiness": 52, "roi_potential": 58, "risk_compliance": 50, "implementation_complexity": 50},
        "reasoning": "Social listening has strategic value but social media data is noisy and privacy regulations apply.",
        "recommendations": ["Build social media monitoring dashboard", "Implement sentiment tracking", "Integrate with marketing workflows"],
    },
    "Recruiting Automation": {
        "scores": {"data_readiness": 52, "technical_feasibility": 55, "organizational_readiness": 50, "roi_potential": 58, "risk_compliance": 52, "implementation_complexity": 52},
        "reasoning": "Recruiting automation has operational value but competitive talent market and technical assessment validity are challenges.",
        "recommendations": ["Build automated resume screening", "Implement interview scheduling automation", "Track source-to-hire metrics"],
    },
    "Location Scoring": {
        "scores": {"data_readiness": 50, "technical_feasibility": 55, "organizational_readiness": 48, "roi_potential": 55, "risk_compliance": 50, "implementation_complexity": 54},
        "reasoning": "Location scoring has major revenue impact but long-term forecasting and data availability vary by market.",
        "recommendations": ["Build multi-factor scoring model", "Integrate demographic and traffic data", "Validate with pilot sites"],
    },
    # ── TechCorp ──
    "Intelligent Resource Allocation": {
        "scores": {"data_readiness": 50, "technical_feasibility": 55, "organizational_readiness": 52, "roi_potential": 60, "risk_compliance": 50, "implementation_complexity": 50},
        "reasoning": "Resource allocation has strong efficiency gains but evolving skills taxonomy and personal preferences complicate optimization.",
        "recommendations": ["Build skills inventory system", "Implement project matching engine", "Establish resource allocation governance"],
    },
    "Site Reliability Monitoring with AI Alerts": {
        "scores": {"data_readiness": 54, "technical_feasibility": 58, "organizational_readiness": 52, "roi_potential": 60, "risk_compliance": 55, "implementation_complexity": 54},
        "reasoning": "SRE monitoring has clear operational value but tool integration complexity and alert fatigue are challenges.",
        "recommendations": ["Implement unified monitoring platform", "Build predictive alerting models", "Automate runbook execution"],
    },
    "Automated Code Review Assistant": {
        "scores": {"data_readiness": 56, "technical_feasibility": 60, "organizational_readiness": 55, "roi_potential": 62, "risk_compliance": 58, "implementation_complexity": 54},
        "reasoning": "Code review automation has strong efficiency gains but false positives and developer adoption are concerns.",
        "recommendations": ["Start with automated style checking", "Build security vulnerability detection", "Implement developer feedback loop"],
    },
    "Expense Fraud Detection": {
        "scores": {"data_readiness": 52, "technical_feasibility": 55, "organizational_readiness": 50, "roi_potential": 58, "risk_compliance": 55, "implementation_complexity": 52},
        "reasoning": "Expense fraud detection has clear ROI but diverse categories and privacy concerns limit scope.",
        "recommendations": ["Build spending pattern baseline", "Implement anomaly detection", "Integrate with expense reporting system"],
    },
    "Contract Review Automation": {
        "scores": {"data_readiness": 50, "technical_feasibility": 54, "organizational_readiness": 48, "roi_potential": 55, "risk_compliance": 58, "implementation_complexity": 52},
        "reasoning": "Contract review automation has efficiency gains but legal interpretation nuance and diverse contract types limit scope.",
        "recommendations": ["Start with standard NDA and MSOA templates", "Build clause risk scoring", "Integrate with contract management system"],
    },
    "Lead Scoring and Prioritization": {
        "scores": {"data_readiness": 54, "technical_feasibility": 58, "organizational_readiness": 52, "roi_potential": 62, "risk_compliance": 55, "implementation_complexity": 54},
        "reasoning": "Lead scoring has strong revenue impact but lead data quality and multi-touch attribution are challenges.",
        "recommendations": ["Implement lead scoring model", "Build CRM integration", "Track conversion attribution"],
    },
    "Tech Talent Recruiting Automation": {
        "scores": {"data_readiness": 52, "technical_feasibility": 55, "organizational_readiness": 50, "roi_potential": 58, "risk_compliance": 52, "implementation_complexity": 52},
        "reasoning": "Tech recruiting automation has operational value but competitive talent market and assessment validity are challenges.",
        "recommendations": ["Build automated resume screening", "Implement coding challenge platform", "Track time-to-hire metrics"],
    },
    "Product Feature Usage Analytics": {
        "scores": {"data_readiness": 58, "technical_feasibility": 62, "organizational_readiness": 55, "roi_potential": 65, "risk_compliance": 58, "implementation_complexity": 55},
        "reasoning": "Feature usage analytics has strong product impact but high-dimensional data and attribution complexity exist.",
        "recommendations": ["Implement event tracking framework", "Build cohort analysis", "Integrate with product roadmap"],
    },
    "Software Asset Management": {
        "scores": {"data_readiness": 55, "technical_feasibility": 58, "organizational_readiness": 52, "roi_potential": 58, "risk_compliance": 60, "implementation_complexity": 52},
        "reasoning": "Software asset management has clear cost savings but decentralized purchases and usage tracking gaps exist.",
        "recommendations": ["Implement software inventory system", "Build license utilization tracking", "Centralize procurement approval"],
    },
    "ML Model Performance Monitoring": {
        "scores": {"data_readiness": 56, "technical_feasibility": 60, "organizational_readiness": 55, "roi_potential": 62, "risk_compliance": 58, "implementation_complexity": 54},
        "reasoning": "ML monitoring is critical for production models but multi-model complexity and drift detection are nuanced.",
        "recommendations": ["Implement model performance dashboard", "Build drift detection alerts", "Automate retraining triggers"],
    },
    "Threat Detection and Response": {
        "scores": {"data_readiness": 52, "technical_feasibility": 55, "organizational_readiness": 50, "roi_potential": 58, "risk_compliance": 62, "implementation_complexity": 55},
        "reasoning": "Threat detection has critical security value but evolving threats and overwhelming alert volume are major challenges.",
        "recommendations": ["Implement SIEM integration", "Build threat correlation engine", "Automate common response playbooks"],
    },
    # ── Manufacturing (additional) ──
    "Workplace Safety Monitoring (Manufacturing)": {
        "scores": {"data_readiness": 58, "technical_feasibility": 62, "organizational_readiness": 55, "roi_potential": 65, "risk_compliance": 60, "implementation_complexity": 55},
        "reasoning": "Safety monitoring has strong ROI but IoT coverage gaps and integration challenges exist.",
        "recommendations": ["Deploy sensors in high-risk areas", "Integrate with safety management", "Build hazard prediction model"],
    },
    "Retail Staff Scheduling Optimization": {
        "scores": {"data_readiness": 58, "technical_feasibility": 62, "organizational_readiness": 55, "roi_potential": 60, "risk_compliance": 58, "implementation_complexity": 55},
        "reasoning": "Staff scheduling optimization has strong ROI from labor cost reduction but variable foot traffic and employee availability are challenges.",
        "recommendations": ["Build foot traffic prediction model", "Implement labor law constraint engine", "Integrate with POS and scheduling systems"],
    },
}


# ── S-A-I-L P7 — deterministic demo customer intelligence ──────────────────────
# Fixed reference date so the seed is fully deterministic (re-seeding produces
# identical data; v2 items 19/21). Demo data is illustrative — it is never
# represented as verified real-company facts, and the seeder only fills empty
# tables (see seed_customer_intelligence): user-entered data is never
# overwritten or duplicated.
SEED_DATE = date(2026, 9, 1)



def _knowledge_mime(filename: str) -> str:
    """Deterministic extension → content-type for seeded knowledge rows."""
    return {
        ".pdf": "application/pdf",
        ".csv": "text/csv",
        ".md": "text/markdown",
        ".txt": "text/plain",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }.get("." + (filename.rsplit(".", 1)[-1].lower() if "." in filename else ""), "application/octet-stream")


def _sd(days: int) -> "date":
    """Deterministic seed date offset from SEED_DATE."""
    return SEED_DATE - timedelta(days=days)


def _sdt(days: int) -> "datetime":
    """Deterministic seed timestamp (midnight UTC of SEED_DATE - days)."""
    return datetime(SEED_DATE.year, SEED_DATE.month, SEED_DATE.day) - timedelta(days=days)


CUSTOMER_INTELLIGENCE = {
    # Workflow: aging technology / EOL + virtualization + modernization.
    "Acme Manufacturing": {
        "vertical": "Manufacturing",
        "technology": [
            {"name": "VMware vSphere 6.5", "vendor": "VMware", "category": "virtualization",
             "version_edition": "6.5 U3", "deployment_model": "virtual_machine", "quantity": 210,
             "footprint": "2 data centers", "purpose": "Core VM hosting for ERP + MES",
             "lifecycle_state": "eol", "support_state": "no_support", "business_criticality": "critical",
             "source": "discovery call", "date_observed": _sd(40), "verification_state": "verified"},
            {"name": "Dell PowerEdge R720", "vendor": "Dell", "category": "hardware",
             "version_edition": "R720", "deployment_model": "bare_metal", "quantity": 48,
             "footprint": "2 data centers", "purpose": "Virtualization compute hosts",
             "lifecycle_state": "eol", "support_state": "no_support", "business_criticality": "high",
             "source": "discovery call", "date_observed": _sd(40), "verification_state": "verified"},
            {"name": "Windows Server 2012 R2", "vendor": "Microsoft", "category": "operating_system",
             "version_edition": "2012 R2", "deployment_model": "virtual_machine", "quantity": 35,
             "purpose": "Application servers (legacy line-of-business)",
             "lifecycle_state": "eol_announced", "support_state": "no_support", "business_criticality": "high",
             "source": "discovery call", "date_observed": _sd(38), "verification_state": "verified"},
            {"name": "Oracle Database 12c", "vendor": "Oracle", "category": "software",
             "version_edition": "12.1.0.2", "deployment_model": "on_premise", "quantity": 12,
             "purpose": "ERP + MES transactional data",
             "lifecycle_state": "previous_generation", "support_state": "support_expiring",
             "business_criticality": "critical", "source": "assessment", "date_observed": _sd(30),
             "verification_state": "verified"},
            {"name": "Cisco Catalyst 3750", "vendor": "Cisco", "category": "networking",
             "deployment_model": "on_premise", "quantity": 24, "purpose": "Factory floor access layer",
             "lifecycle_state": "previous_generation", "support_state": "under_support",
             "business_criticality": "medium", "source": "assessment", "date_observed": _sd(30),
             "verification_state": "verified"},
            {"name": "SAP S/4HANA", "vendor": "SAP", "category": "software",
             "version_edition": "2022", "deployment_model": "private_cloud", "purpose": "ERP core",
             "lifecycle_state": "current", "support_state": "under_support",
             "business_criticality": "critical", "source": "assessment", "date_observed": _sd(25),
             "verification_state": "verified"},
            {"name": "Nutanix AHV", "vendor": "Nutanix", "category": "virtualization",
             "deployment_model": "virtual_machine", "purpose": "Evaluating as refresh platform",
             "lifecycle_state": "current", "support_state": "under_support", "business_criticality": "medium",
             "source": "competitive call", "date_observed": _sd(10), "verification_state": "inferred",
             "confidence": 0.7},
            {"name": "Microsoft 365", "vendor": "Microsoft", "category": "software",
             "deployment_model": "saas", "purpose": "Productivity + collaboration",
             "lifecycle_state": "current", "support_state": "under_support", "business_criticality": "medium",
             "source": "assessment", "date_observed": _sd(20), "verification_state": "verified"},
            {"name": "VMware vCenter Server 6.5", "vendor": "VMware", "category": "management_tool",
             "deployment_model": "on_premise", "quantity": 2, "footprint": "2 data centers",
             "purpose": "Manages the vSphere estate (VMs, hosts, storage policies)",
             "lifecycle_state": "eol", "support_state": "no_support", "business_criticality": "high",
             "source": "discovery call", "date_observed": _sd(40), "verification_state": "verified"},
            {"name": "Cisco UCS C240", "vendor": "Cisco", "category": "hardware",
             "version_edition": "C240 M5", "deployment_model": "bare_metal", "quantity": 20,
             "footprint": "2 data centers", "purpose": "Virtualization compute hosts (second fleet)",
             "lifecycle_state": "current", "support_state": "under_support", "business_criticality": "high",
             "source": "discovery call", "date_observed": _sd(40), "verification_state": "verified"},
            {"name": "NetApp ONTAP", "vendor": "NetApp", "category": "storage",
             "version_edition": "9.12", "deployment_model": "on_premise", "quantity": 2,
             "footprint": "shared LUNs across both DCs", "purpose": "Block storage for the virtualization estate",
             "lifecycle_state": "current", "support_state": "under_support", "business_criticality": "high",
             "source": "discovery call", "date_observed": _sd(38), "verification_state": "verified"},
            {"name": "Microsoft Active Directory", "vendor": "Microsoft", "category": "other",
             "version_edition": "Server 2016", "deployment_model": "on_premise", "quantity": 6,
             "purpose": "Identity + access for the plant and office domains",
             "lifecycle_state": "current", "support_state": "under_support", "business_criticality": "high",
             "source": "assessment", "date_observed": _sd(28), "verification_state": "verified"},
            {"name": "Veeam Backup & Replication", "vendor": "Veeam", "category": "management_tool",
             "deployment_model": "on_premise", "quantity": 1, "purpose": "Protects the vSphere fleet (backup + DR)",
             "lifecycle_state": "current", "support_state": "under_support", "business_criticality": "high",
             "source": "discovery call", "date_observed": _sd(30), "verification_state": "verified"},
        ],
        "sales_notes": [
            {"category": "discovery", "title": "IT discovery: 200+ VMs on vSphere 6.5",
             "content": "Walked the platform team through the estate. ~210 production VMs on "
                        "vSphere 6.5 across 48 R720 hosts. No path to a supported upgrade in place; "
                        "team estimates a 6-9 month refresh with the right platform.",
             "author": "j.rivera", "source": "on-site discovery", "note_date": _sd(35),
             "verification_state": "verified",
             "link_tech": ["VMware vSphere 6.5", "Dell PowerEdge R720"],
             "link_use_cases": ["Manufacturing IT Infrastructure Monitoring"]},
            {"category": "competitive", "title": "Nutanix shortlisted for the refresh",
             "content": "IT presented Nutanix AHV as a candidate to consolidate compute + storage. "
                        "Budget not yet committed; decision expected in the FY27 planning cycle.",
             "author": "j.rivera", "source": "competitive call", "note_date": _sd(12),
             "verification_state": "verified", "link_tech": ["Nutanix AHV"]},
            {"category": "risk", "title": "vSphere 6.5 EOL — no security patches",
             "content": "vSphere 6.5 left vendor support; security patches are no longer available. "
                        "Two unpatched CVEs flagged by the security team in the last quarter.",
             "author": "j.rivera", "source": "security review", "note_date": _sd(20),
             "verification_state": "verified", "link_tech": ["VMware vSphere 6.5"]},
            {"category": "account_observation", "title": "New CIO prioritizes infra refresh",
             "content": "Newly appointed CIO (started 6 months ago) has signaled that infrastructure "
                        "modernization is a top-3 priority and is tying it to the FY27 budget.",
             "author": "m.chen", "source": "executive briefing", "note_date": _sd(8),
             "verification_state": "verified"},
            {"category": "meeting", "title": "Refresh workshop — 24-month horizon",
             "content": "Ran a half-day workshop with IT + finance. Consensus on a 24-month refresh "
                        "horizon; finance wants a phased, risk-based sequencing (EOL + critical first). "
                        "Interpretation: strong buying intent but a multi-stage deal.",
             "author": "j.rivera", "source": "workshop notes", "note_date": _sd(5),
             "verification_state": "inferred"},
        ],
        "knowledge": [
            {"knowledge_type": "file", "file_name": "it-infrastructure-overview.pdf",
             "file_data": b"S-A-I-L demo knowledge (illustrative): Acme Manufacturing - IT infrastructure overview. [DEMO - not a real company document]",
             "uploaded_at": _sdt(2), "processed": 1, "ingestion_status": "processed",
             "ingested_at": _sdt(2), "classification": "reference"},
            {"knowledge_type": "csv", "file_name": "vendor-support-contracts.csv",
             "file_data": b"S-A-I-L demo knowledge (illustrative): Acme Manufacturing - vendor support contract end dates. [DEMO - not a real company document]",
             "uploaded_at": _sdt(10), "processed": 1, "ingestion_status": "processed",
             "ingested_at": _sdt(9), "classification": "contract"},
            {"knowledge_type": "file", "file_name": "factory-network-diagram.pdf",
             "file_data": b"S-A-I-L demo knowledge (illustrative): Acme Manufacturing - factory network diagram. [DEMO - not a real company document]",
             "uploaded_at": _sdt(5), "processed": 0, "ingestion_status": "pending",
             "ingested_at": None, "classification": None},
        ],
        "dependencies": [
            # A coherent virtualization environment (source -> target).
            {"source": "VMware vCenter Server 6.5", "target": "VMware vSphere 6.5", "type": "manages"},
            {"source": "VMware vSphere 6.5", "target": "Dell PowerEdge R720", "type": "runs_on"},
            {"source": "VMware vSphere 6.5", "target": "Cisco UCS C240", "type": "runs_on"},
            {"source": "VMware vSphere 6.5", "target": "NetApp ONTAP", "type": "consumes_storage"},
            {"source": "Windows Server 2012 R2", "target": "VMware vSphere 6.5", "type": "runs_on"},
            {"source": "Oracle Database 12c", "target": "Windows Server 2012 R2", "type": "runs_on"},
            {"source": "Veeam Backup & Replication", "target": "VMware vSphere 6.5", "type": "protects"},
            {"source": "Microsoft 365", "target": "Microsoft Active Directory", "type": "integrates_with"},
        ],
    },
    # Workflow: security gaps + compliance + competitive platforms.
    "GlobalBank Financial Services": {
        "vertical": "Financial Services",
        "technology": [
            {"name": "IBM Z14 Mainframe", "vendor": "IBM", "category": "hardware",
             "version_edition": "Z14", "deployment_model": "bare_metal", "quantity": 2,
             "footprint": "1 data center", "purpose": "Core banking batch processing",
             "lifecycle_state": "current", "support_state": "under_support", "business_criticality": "critical",
             "source": "discovery call", "date_observed": _sd(45), "verification_state": "verified"},
            {"name": "Oracle RAC 11g", "vendor": "Oracle", "category": "software",
             "version_edition": "11.2.0.4", "deployment_model": "on_premise", "quantity": 8,
             "purpose": "Transactional databases (legacy core banking)",
             "lifecycle_state": "previous_generation", "support_state": "support_expiring",
             "business_criticality": "critical", "source": "assessment", "date_observed": _sd(38),
             "verification_state": "verified"},
            {"name": "Palo Alto PA-8000", "vendor": "Palo Alto Networks", "category": "security",
             "deployment_model": "on_premise", "quantity": 4, "purpose": "Perimeter firewall / NGFW",
             "lifecycle_state": "current", "support_state": "under_support", "business_criticality": "high",
             "source": "assessment", "date_observed": _sd(32), "verification_state": "verified"},
            {"name": "Splunk Enterprise", "vendor": "Splunk", "category": "security",
             "deployment_model": "private_cloud", "quantity": 1, "purpose": "SIEM / log analytics",
             "lifecycle_state": "current", "support_state": "under_support", "business_criticality": "high",
             "source": "assessment", "date_observed": _sd(32), "verification_state": "verified"},
            {"name": "Tenable Nessus", "vendor": "Tenable", "category": "security",
             "deployment_model": "on_premise", "quantity": 1, "purpose": "Vulnerability scanning",
             "lifecycle_state": "current", "support_state": "under_support", "business_criticality": "medium",
             "source": "assessment", "date_observed": _sd(28), "verification_state": "verified"},
            {"name": "Core Banking (proprietary)", "vendor": "Internal", "category": "software",
             "deployment_model": "on_premise", "purpose": "Customer accounts + ledger",
             "lifecycle_state": "previous_generation", "support_state": "under_support",
             "business_criticality": "critical", "source": "vendor assessment", "date_observed": _sd(26),
             "verification_state": "inferred", "confidence": 0.6},
            {"name": "Azure Government (evaluating)", "vendor": "Microsoft", "category": "cloud_platform",
             "deployment_model": "public_cloud", "purpose": "Target for non-core workloads",
             "lifecycle_state": "current", "support_state": "under_support", "business_criticality": "high",
             "source": "RFP", "date_observed": _sd(14), "verification_state": "inferred", "confidence": 0.5},
            {"name": "Fortinet FortiGate", "vendor": "Fortinet", "category": "security",
             "deployment_model": "on_premise", "quantity": 12, "purpose": "Branch + DMZ edge firewalls",
             "lifecycle_state": "previous_generation", "support_state": "support_expiring",
             "business_criticality": "high", "source": "assessment", "date_observed": _sd(24),
             "verification_state": "verified"},
            {"name": "Microsoft Active Directory", "vendor": "Microsoft", "category": "other",
             "version_edition": "Server 2019", "deployment_model": "on_premise", "quantity": 4,
             "purpose": "Identity + access for branch and datacenter staff",
             "lifecycle_state": "current", "support_state": "under_support", "business_criticality": "high",
             "source": "assessment", "date_observed": _sd(26), "verification_state": "verified"},
            {"name": "Veeam Backup & Replication", "vendor": "Veeam", "category": "management_tool",
             "deployment_model": "on_premise", "quantity": 1, "purpose": "Protects the core banking workloads",
             "lifecycle_state": "current", "support_state": "under_support", "business_criticality": "high",
             "source": "assessment", "date_observed": _sd(24), "verification_state": "verified"},
        ],
        "sales_notes": [
            {"category": "risk", "title": "PCI-DSS audit flagged legacy systems",
             "content": "Latest PCI-DSS audit flagged 3 legacy systems lacking current patching, "
                        "including the Oracle 11g RAC cluster. Remediation plan due to the regulator "
                        "within 90 days.",
             "author": "a.okafor", "source": "audit findings", "note_date": _sd(30),
             "verification_state": "verified", "link_tech": ["Oracle RAC 11g"]},
            {"category": "competitive", "title": "CrowdStrike PoC vs Splunk",
             "content": "A CrowdStrike Falcon PoC is in progress alongside the existing Splunk SIEM. "
                        "The security team is weighing endpoint-detection coverage; Splunk renewal is "
                        "up in the next quarter.",
             "author": "a.okafor", "source": "competitive call", "note_date": _sd(15),
             "verification_state": "verified", "link_tech": ["Splunk Enterprise"]},
            {"category": "discovery", "title": "Security posture: EOL devices in DMZ",
             "content": "Posture review found 2 EOL network devices in the DMZ still running a prior "
                        "FortiGate firmware. Security wants them replaced or segmented this year.",
             "author": "a.okafor", "source": "posture review", "note_date": _sd(22),
             "verification_state": "verified", "link_tech": ["Fortinet FortiGate"]},
            {"category": "initiative", "title": "Cloud migration approved for non-core",
             "content": "The board approved a cloud-migration program for non-core workloads. Azure "
                        "Government is the leading platform; core banking stays on-prem for the "
                        "foreseeable future.",
             "author": "m.chen", "source": "program office", "note_date": _sd(9),
             "verification_state": "verified", "link_tech": ["Azure Government (evaluating)"],
             "link_use_cases": ["Automated Regulatory Reporting"]},
            {"category": "objection", "title": "Compliance resistance to multi-cloud",
             "content": "The compliance team raised concerns that a multi-cloud footprint increases "
                        "audit complexity and data-residency risk. This is the main blocker for a "
                        "faster migration — interpretation: address with a single-region, single-cloud "
                        "posture to de-risk.",
             "author": "a.okafor", "source": "objection log", "note_date": _sd(6),
             "verification_state": "inferred"},
        ],
        "knowledge": [
            {"knowledge_type": "file", "file_name": "pci-dss-audit-2026.pdf",
             "file_data": b"S-A-I-L demo knowledge (illustrative): GlobalBank - PCI-DSS audit findings summary. [DEMO - not a real company document]",
             "uploaded_at": _sdt(3), "processed": 1, "ingestion_status": "processed",
             "ingested_at": _sdt(3), "classification": "audit"},
            {"knowledge_type": "csv", "file_name": "dmz-network-inventory.csv",
             "file_data": b"S-A-I-L demo knowledge (illustrative): GlobalBank - DMZ device inventory. [DEMO - not a real company document]",
             "uploaded_at": _sdt(12), "processed": 1, "ingestion_status": "processed",
             "ingested_at": _sdt(11), "classification": "inventory"},
            {"knowledge_type": "file", "file_name": "security-architecture-notes.pdf",
             "file_data": b"S-A-I-L demo knowledge (illustrative): GlobalBank - security architecture notes. [DEMO - not a real company document]",
             "uploaded_at": _sdt(7), "processed": 0, "ingestion_status": "pending",
             "ingested_at": None, "classification": None},
        ],
        "dependencies": [
            {"source": "Oracle RAC 11g", "target": "IBM Z14 Mainframe", "type": "runs_on"},
            {"source": "Core Banking (proprietary)", "target": "Oracle RAC 11g", "type": "depends_on"},
            {"source": "Veeam Backup & Replication", "target": "IBM Z14 Mainframe", "type": "protects"},
            {"source": "Veeam Backup & Replication", "target": "Oracle RAC 11g", "type": "protects"},
            {"source": "Splunk Enterprise", "target": "Fortinet FortiGate", "type": "integrates_with"},
            {"source": "Fortinet FortiGate", "target": "Microsoft Active Directory", "type": "integrates_with"},
        ],
    },
    # Workflow: cloud adoption + AI initiatives + mixed vendors.
    "TechCorp Solutions": {
        "vertical": "Technology",
        "technology": [
            {"name": "AWS EKS", "vendor": "Amazon Web Services", "category": "cloud_platform",
             "deployment_model": "public_cloud", "quantity": 6, "footprint": "2 regions",
             "purpose": "Production microservice hosting",
             "lifecycle_state": "current", "support_state": "under_support", "business_criticality": "critical",
             "source": "discovery call", "date_observed": _sd(42), "verification_state": "verified"},
            {"name": "Google GKE", "vendor": "Google Cloud", "category": "cloud_platform",
             "deployment_model": "public_cloud", "quantity": 2, "purpose": "Analytics + batch workloads",
             "lifecycle_state": "current", "support_state": "under_support", "business_criticality": "medium",
             "source": "discovery call", "date_observed": _sd(42), "verification_state": "verified"},
            {"name": "Snowflake", "vendor": "Snowflake", "category": "data_platform",
             "deployment_model": "saas", "purpose": "Enterprise data warehouse",
             "lifecycle_state": "current", "support_state": "under_support", "business_criticality": "high",
             "source": "assessment", "date_observed": _sd(34), "verification_state": "verified"},
            {"name": "Databricks", "vendor": "Databricks", "category": "data_platform",
             "deployment_model": "saas", "purpose": "ML feature store + lakehouse",
             "lifecycle_state": "current", "support_state": "under_support", "business_criticality": "high",
             "source": "assessment", "date_observed": _sd(34), "verification_state": "verified"},
            {"name": "Jenkins", "vendor": "Jenkins", "category": "management_tool",
             "deployment_model": "on_premise", "quantity": 3, "purpose": "CI build + deploy pipelines",
             "lifecycle_state": "previous_generation", "support_state": "under_support",
             "business_criticality": "medium", "source": "assessment", "date_observed": _sd(28),
             "verification_state": "verified"},
            {"name": "Datadog", "vendor": "Datadog", "category": "management_tool",
             "deployment_model": "saas", "purpose": "Observability (APM + infra + logs)",
             "lifecycle_state": "current", "support_state": "under_support", "business_criticality": "high",
             "source": "assessment", "date_observed": _sd(24), "verification_state": "verified"},
            {"name": "Internal LLM Platform", "vendor": "In-house", "category": "ai_technology",
             "deployment_model": "container", "purpose": "GenAI serving + RAG for support",
             "lifecycle_state": "current", "support_state": "under_support", "business_criticality": "medium",
             "source": "architecture review", "date_observed": _sd(16), "verification_state": "inferred",
             "confidence": 0.6},
            {"name": "VMware vSAN (on-prem pilot)", "vendor": "VMware", "category": "storage",
             "deployment_model": "virtual_machine", "quantity": 1, "purpose": "On-prem DR pilot",
             "lifecycle_state": "previous_generation", "support_state": "support_expiring",
             "business_criticality": "low", "source": "pilot notes", "date_observed": _sd(12),
             "verification_state": "verified"},
            {"name": "Red Hat OpenShift", "vendor": "Red Hat", "category": "infrastructure",
             "version_edition": "4.16", "deployment_model": "private_cloud", "quantity": 3,
             "footprint": "1 on-prem cluster + EKS", "purpose": "On-prem Kubernetes estate (workload modernization)",
             "lifecycle_state": "current", "support_state": "under_support", "business_criticality": "high",
             "source": "architecture review", "date_observed": _sd(20), "verification_state": "verified"},
            {"name": "Red Hat Enterprise Linux", "vendor": "Red Hat", "category": "operating_system",
             "version_edition": "9.4", "deployment_model": "bare_metal", "quantity": 60,
             "purpose": "Server OS across the on-prem + OpenShift control planes",
             "lifecycle_state": "current", "support_state": "under_support", "business_criticality": "high",
             "source": "architecture review", "date_observed": _sd(20), "verification_state": "verified"},
            {"name": "Ansible Automation Platform", "vendor": "Red Hat", "category": "management_tool",
             "version_edition": "2.5", "deployment_model": "on_premise", "quantity": 1,
             "purpose": "Configuration + deployment automation for RHEL and the estate",
             "lifecycle_state": "current", "support_state": "under_support", "business_criticality": "medium",
             "source": "architecture review", "date_observed": _sd(18), "verification_state": "verified"},
            {"name": "NetApp Trident", "vendor": "NetApp", "category": "storage",
             "version_edition": "22.6", "deployment_model": "container", "quantity": 3,
             "purpose": "Kubernetes CSI driver — persistent storage for OpenShift workloads",
             "lifecycle_state": "current", "support_state": "under_support", "business_criticality": "high",
             "source": "architecture review", "date_observed": _sd(18), "verification_state": "verified"},
            {"name": "NetApp ONTAP", "vendor": "NetApp", "category": "storage",
             "version_edition": "9.12", "deployment_model": "on_premise", "quantity": 2,
             "purpose": "Shared storage backend for the OpenShift cluster",
             "lifecycle_state": "current", "support_state": "under_support", "business_criticality": "high",
             "source": "architecture review", "date_observed": _sd(18), "verification_state": "verified"},
            {"name": "Dell PowerEdge XE9680", "vendor": "Dell", "category": "hardware",
             "deployment_model": "bare_metal", "quantity": 8, "footprint": "GPU node pool",
             "purpose": "AI inference + training node pool",
             "lifecycle_state": "current", "support_state": "under_support", "business_criticality": "high",
             "source": "architecture review", "date_observed": _sd(15), "verification_state": "verified"},
            {"name": "NVIDIA A100 GPUs", "vendor": "NVIDIA", "category": "ai_technology",
             "version_edition": "A100 80GB", "deployment_model": "bare_metal", "quantity": 16,
             "footprint": "2 per XE9680 node", "purpose": "Accelerator pool for the internal LLM platform",
             "lifecycle_state": "current", "support_state": "under_support", "business_criticality": "high",
             "source": "architecture review", "date_observed": _sd(15), "verification_state": "verified"},
            {"name": "PostgreSQL", "vendor": "PostgreSQL", "category": "data_platform",
             "version_edition": "15", "deployment_model": "on_premise", "quantity": 6,
             "purpose": "Transactional databases for the service layer (OpenShift + bare-metal)",
             "lifecycle_state": "current", "support_state": "under_support", "business_criticality": "high",
             "source": "architecture review", "date_observed": _sd(14), "verification_state": "verified"},
        ],
        "sales_notes": [
            {"category": "discovery", "title": "Multi-cloud estate + FinOps gap",
             "content": "40+ services across AWS (EKS) and GCP (GKE). Cost visibility is manual "
                        "spreadheets; no FinOps tooling. Engineering wants unified, per-team "
                        "showback before the next budget cycle.",
             "author": "s.patel", "source": "discovery", "note_date": _sd(36),
             "verification_state": "verified",
             "link_tech": ["AWS EKS", "Google GKE", "Databricks"]},
            {"category": "initiative", "title": "GenAI support assistant in pilot",
             "content": "A GenAI assistant for support-ticket triage is in pilot (Q3), built on the "
                        "internal LLM platform. Target: 40% reduction in handling time. Success "
                        "metrics agreed with the CS leadership team.",
             "author": "s.patel", "source": "initiative review", "note_date": _sd(18),
             "verification_state": "verified", "link_tech": ["Internal LLM Platform"],
             "link_use_cases": ["Automated Customer Support Triage"]},
            {"category": "technical_discussion", "title": "EKS autoscaling under peak load",
             "content": "Cluster autoscaler is slow to scale during evening peaks, causing p99 "
                        "latency spikes. Engineering is evaluating Karpenter + a right-sizing "
                        "review of the node pools.",
             "author": "s.patel", "source": "technical deep-dive", "note_date": _sd(11),
             "verification_state": "verified", "link_tech": ["AWS EKS"],
             "link_use_cases": ["Site Reliability Monitoring with AI Alerts"]},
            {"category": "competitive", "title": "Datadog vs Grafana consolidation",
             "content": "Evaluating Datadog vs a Grafana-based stack for observability consolidation. "
                        "Datadog's per-host pricing is the main objection; a 12-month PoC is planned.",
             "author": "s.patel", "source": "competitive call", "note_date": _sd(7),
             "verification_state": "verified", "link_tech": ["Datadog"]},
            {"category": "opportunity", "title": "Snowflake capacity expansion",
             "content": "Data warehouse growth is ~30% YoY; the current Snowflake capacity tier will "
                        "be exceeded within two quarters. Expansion + a storage-tier review is a near-term "
                        "opportunity.",
             "author": "s.patel", "source": "capacity review", "note_date": _sd(4),
             "verification_state": "verified", "link_tech": ["Snowflake"]},
        ],
        "knowledge": [
            {"knowledge_type": "csv", "file_name": "cloud-cost-breakdown.csv",
             "file_data": b"S-A-I-L demo knowledge (illustrative): TechCorp Solutions - cloud cost breakdown by service. [DEMO - not a real company document]",
             "uploaded_at": _sdt(2), "processed": 1, "ingestion_status": "processed",
             "ingested_at": _sdt(2), "classification": "cost"},
            {"knowledge_type": "file", "file_name": "engineering-architecture.pdf",
             "file_data": b"S-A-I-L demo knowledge (illustrative): TechCorp Solutions - engineering architecture overview. [DEMO - not a real company document]",
             "uploaded_at": _sdt(15), "processed": 1, "ingestion_status": "processed",
             "ingested_at": _sdt(14), "classification": "architecture"},
            {"knowledge_type": "file", "file_name": "genai-pilot-readout.md",
             "file_data": b"S-A-I-L demo knowledge (illustrative): TechCorp Solutions - GenAI pilot readout. [DEMO - not a real company document]",
             "uploaded_at": _sdt(4), "processed": 0, "ingestion_status": "pending",
             "ingested_at": None, "classification": None},
        ],
        "dependencies": [
            # A coherent hybrid + AI environment (source -> target).
            {"source": "Red Hat OpenShift", "target": "Red Hat Enterprise Linux", "type": "runs_on"},
            {"source": "Red Hat OpenShift", "target": "NetApp Trident", "type": "consumes_storage"},
            {"source": "NetApp Trident", "target": "NetApp ONTAP", "type": "integrates_with"},
            {"source": "Internal LLM Platform", "target": "Red Hat OpenShift", "type": "runs_on"},
            {"source": "Internal LLM Platform", "target": "NVIDIA A100 GPUs", "type": "consumes_compute"},
            {"source": "NVIDIA A100 GPUs", "target": "Dell PowerEdge XE9680", "type": "runs_on"},
            {"source": "Ansible Automation Platform", "target": "Red Hat Enterprise Linux", "type": "automates"},
            {"source": "PostgreSQL", "target": "Red Hat OpenShift", "type": "runs_on"},
        ],
    },
}


def _dimension_list(flat_scores):
    """Flat {snake_key: 0-100} scores -> canonical [{name, score, weight}]."""
    from backend.services.scoring import ScoringService

    weights = {d["name"]: d["weight"] for d in ScoringService.DIMENSIONS}
    norm = ScoringService.extract_dimension_scores(flat_scores)
    return [
        {"name": name, "score": float(norm[name]), "weight": weights[name]}
        for name in ScoringService.DIMENSIONS_NAME_ORDER
        if name in norm
    ]


def _baseline_history(db: Session, uc, scoring: dict, now):
    """Enriched fresh-DB baseline: a 3-round scoring history.

    Writes the authoritative score_history TABLE rows (21d/7d/now,
    deterministic movement of 3..6 points anchored on the current round)
    and the legacy JSON column in the app-read format (scored_at + score
    keys) so last-state analytics, cohort trends, and the drill-down chart
    show real movement instead of a single snapshot / zero-valued chart.
    """
    from backend.models.collaboration import ScoreHistory

    overall = float(uc.overall_score)
    delta = 3 + (uc.id % 4)  # 3..6 points of movement over 21 days
    round_a = round(max(10.0, min(92.0, overall - delta)), 1)
    round_b = round(max(10.0, min(92.0, overall - delta / 2.0)), 1)
    t_a = now - timedelta(days=21)
    t_b = now - timedelta(days=7)
    dims = _dimension_list(scoring.get("scores", {}))
    reasoning = scoring.get("reasoning")
    recs = scoring.get("recommendations", [])

    rounds = ((t_a, round_a), (t_b, round_b), (now, overall))
    for t, s in rounds:
        db.add(
            ScoreHistory(
                use_case_id=uc.id,
                score=s,
                scored_at=t,
                scored_by="admin",
                is_manual=0,
                status="approved",
                dimension_scores=dims,
                reasoning=reasoning,
            )
        )
    uc.score_history = [
        {
            "scored_at": t.isoformat(),
            "date": t.isoformat(),
            "score": s,
            "overall_score": s,
            "scores": scoring.get("scores", {}),
            "reasoning": reasoning,
            "recommendations": recs,
        }
        for t, s in rounds
    ]


def seed_database(db: Session, reset: bool = False) -> int:
    """Seed the database with sample use cases organized by customer.

    Returns the number of use cases created/updated.
    """
    if reset:
        db.query(AIPrediction).delete()
        db.query(CustomerAssessment).delete()
        db.query(UseCase).delete()
        db.query(Department).delete()
        db.query(Customer).delete()
        db.commit()

    created = 0
    for customer_data in CUSTOMERS:
        customer = db.query(Customer).filter(Customer.name == customer_data["name"]).first()
        if customer:
            customer.description = customer_data["description"]
            print(f"  Updated customer: {customer.name}")
        else:
            customer = Customer(name=customer_data["name"], description=customer_data["description"])
            db.add(customer)
            db.flush()
            print(f"  Created customer: {customer.name}")

        # Ensure the customer's active assessment round exists (one per customer)
        active_assessment = (
            db.query(CustomerAssessment)
            .filter(
                CustomerAssessment.customer_id == customer.id,
                CustomerAssessment.status == "active",
            )
            .first()
        )
        if active_assessment is None:
            count = (
                db.query(CustomerAssessment)
                .filter(CustomerAssessment.customer_id == customer.id)
                .count()
            )
            active_assessment = CustomerAssessment(
                customer_id=customer.id,
                name=f"{customer.name} — Assessment {count + 1}",
                status="active",
                created_at=datetime.now(UTC),
            )
            db.add(active_assessment)
            db.flush()

        for dept_data in customer_data["departments"]:
            dept = db.query(Department).filter(
                Department.name == dept_data["name"],
                Department.customer_id == customer.id,
            ).first()
            if dept:
                print(f"  Updated department: {dept.name} (customer: {customer.name})")
            else:
                dept = Department(name=dept_data["name"], customer_id=customer.id)
                db.add(dept)
                db.flush()
                print(f"  Created department: {dept.name} under {customer.name}")

            for uc_data in dept_data["use_cases"]:
                existing = db.query(UseCase).filter(UseCase.title == uc_data["title"]).first()

                if existing:
                    for key, value in uc_data.items():
                        if key in ("scored", "overall_score", "scores", "reasoning", "recommendations"):
                            continue
                        setattr(existing, key, value)

                    if existing.customer_id != customer.id:
                        existing.customer_id = customer.id
                    if existing.department_id != dept.id:
                        existing.department_id = dept.id
                    if existing.assessment_id is None:
                        existing.assessment_id = active_assessment.id

                    # Apply scoring data for ALL use cases (not just flagged "scored")
                    if uc_data["title"] in SCORING_DATA:
                        scoring = SCORING_DATA[uc_data["title"]]
                        now = datetime.now(UTC)

                        if not existing.score_history:
                            existing.score_history = []

                        # A re-seed is a new scoring round: the current round
                        # lands in the authoritative score_history table, and
                        # the legacy JSON column keeps the app-read format
                        # (scored_at + score keys).
                        from backend.models.collaboration import ScoreHistory

                        score_value = uc_data.get("overall_score", 0)
                        db.add(ScoreHistory(
                            use_case_id=existing.id,
                            score=score_value,
                            scored_at=now,
                            scored_by="admin",
                            is_manual=0,
                            status="approved",
                            dimension_scores=_dimension_list(scoring.get("scores", {})),
                            reasoning=scoring.get("reasoning"),
                        ))
                        score_entry = {
                            "scored_at": now.isoformat(),
                            "date": now.isoformat(),
                            "score": score_value,
                            "overall_score": score_value,
                            "scores": scoring["scores"],
                            "reasoning": scoring["reasoning"],
                            "recommendations": scoring["recommendations"],
                        }
                        existing.score_history = existing.score_history[-4:] + [score_entry]

                        existing.scores = scoring["scores"]
                        existing.overall_score = score_value
                        existing.scored_at = now

                    db.flush()
                    print(f"  Updated: {uc_data['title']}")
                else:
                    use_case = UseCase(
                        title=uc_data["title"],
                        description=uc_data["description"],
                        customer_id=customer.id,
                        department_id=dept.id,
                        department=dept_data["name"],
                        status=uc_data.get("status", "draft"),
                        assessment_id=active_assessment.id,
                        goals=uc_data.get("goals", []),
                        challenges=uc_data.get("challenges", []),
                        pain_points=uc_data.get("pain_points", []),
                        impact_category=uc_data.get("impact_category"),
                        impact_description=uc_data.get("impact_description", ""),
                        estimated_savings=uc_data.get("estimated_savings", 0),
                        estimated_revenue=uc_data.get("estimated_revenue", 0),
                        timeline_estimate=uc_data.get("timeline_estimate"),
                    )

                    # Apply scoring for ALL use cases
                    if uc_data["title"] in SCORING_DATA:
                        scoring = SCORING_DATA[uc_data["title"]]
                        now = datetime.now(UTC)
                        use_case.scores = scoring["scores"]
                        use_case.overall_score = uc_data.get("overall_score")
                        use_case.scored_at = now

                    db.add(use_case)
                    created += 1
                    db.flush()  # id available for the history rows

                    # Enriched baseline: multi-round scoring history so a
                    # fresh DB shows real movement in last-state analytics,
                    # cohort trends, and the drill-down chart.
                    if uc_data["title"] in SCORING_DATA and use_case.overall_score is not None:
                        _baseline_history(db, use_case, SCORING_DATA[uc_data["title"]], use_case.scored_at)

                    print(f"  Created: {uc_data['title']}")

    db.commit()
    return created


def seed_customer_intelligence(db: Session, reset: bool = False) -> dict:
    """S-A-I-L P7 — deterministic demo customer-intelligence seeding.

    Seeds each demo customer's Technology Inventory + Sales Notes ONLY when
    that customer has none yet (v2 items 19/21: "seeds fill empty tables
    only — never overwrite user-entered data"). Re-seeding a DB that already
    holds user data is a no-op (idempotent, non-destructive). ``reset=True``
    (used by ``--reset``) clears the S-A-I-L tables first, then seeds.

    Deterministic: all content/dates derive from the fixed ``SEED_DATE``
    (see CUSTOMER_INTELLIGENCE) — re-seeding produces identical data.
    Junctions are resolved by tech NAME / use-case TITLE, so links stay
    consistent even when the customer's records are user-created.

    Returns ``{"technology": n, "sales_notes": n, "knowledge": n,
    "dependencies": n}`` counts.
    """
    stats = {"technology": 0, "sales_notes": 0, "knowledge": 0, "dependencies": 0}

    if reset:
        # Explicitly clear the M2M junction tables first (SQLite FK cascade is
        # not guaranteed on every connection), then the S-A-I-L rows.
        db.execute(sales_note_technologies.delete())
        db.execute(sales_note_use_cases.delete())
        db.query(SalesNote).delete()
        db.query(TechnologyDependency).delete()
        db.query(CustomerTechnology).delete()
        db.query(CustomerKnowledge).delete()
        db.commit()

    for customer_data in CUSTOMERS:
        name = customer_data["name"]
        intel = CUSTOMER_INTELLIGENCE.get(name)
        if intel is None:
            continue
        customer = db.query(Customer).filter(Customer.name == name).first()
        if customer is None:
            continue

        # Business context: vertical (only when unset — never overwrite).
        if customer.vertical is None and intel.get("vertical"):
            customer.vertical = intel["vertical"]

        # ── Technology Inventory — seed only when the customer has none ──
        tech_items = (
            db.query(CustomerTechnology)
            .filter(CustomerTechnology.customer_id == customer.id)
            .order_by(CustomerTechnology.id)
            .all()
        )
        if not tech_items:
            for t in intel.get("technology", []):
                item = CustomerTechnology(customer_id=customer.id, **t)
                db.add(item)
                tech_items.append(item)
                stats["technology"] += 1
            db.flush()  # ids available for junctions
        tech_by_name = {t.name: t for t in tech_items}

        # ── Sales Notes — seed only when the customer has none ──
        note_count = (
            db.query(SalesNote)
            .filter(SalesNote.customer_id == customer.id)
            .count()
        )
        if note_count == 0:
            use_cases = (
                db.query(UseCase)
                .filter(UseCase.customer_id == customer.id)
                .all()
            )
            uc_by_title = {u.title: u for u in use_cases}
            for n in intel.get("sales_notes", []):
                note_data = {k: v for k, v in n.items() if k not in ("link_tech", "link_use_cases")}
                note = SalesNote(customer_id=customer.id, **note_data)
                for tname in n.get("link_tech", []):
                    if tname in tech_by_name:
                        note.related_technologies.append(tech_by_name[tname])
                for title in n.get("link_use_cases", []):
                    if title in uc_by_title:
                        note.related_use_cases.append(uc_by_title[title])
                db.add(note)
                stats["sales_notes"] += 1
            db.flush()

        # ── Customer Knowledge — seed only when the customer has none ──
        kn_count = (
            db.query(CustomerKnowledge)
            .filter(CustomerKnowledge.customer_id == customer.id)
            .count()
        )
        if kn_count == 0:
            for k in intel.get("knowledge", []):
                # PLAN.md part 43 (Docling normalization layer): derive the
                # processing-status contract from the seed's legacy
                # ``processed`` flag so demo rows carry the same shape the
                # upload path produces. Deterministic Markdown placeholder
                # for processed rows (demo-labeled; the seed's existing
                # convention for demo bytes) — the seed never invokes
                # Docling.
                processed_flag = 1 if k.get("processed") else 0
                k = dict(k)
                k.setdefault(
                    "original_content_type",
                    _knowledge_mime(k["file_name"]),
                )
                k.setdefault("normalized_format", "markdown")
                k.setdefault(
                    "processing_status",
                    "READY" if processed_flag else "UPLOADED",
                )
                if processed_flag:
                    k.setdefault("processor", "docling")
                    k.setdefault(
                        "normalized_content",
                        f"<!-- S-A-I-L demo knowledge (illustrative, "
                        f"normalized Markdown placeholder) -->\n\n# "
                        f"{k['file_name']}\n\nDemo normalized content for "
                        f"{k['file_name']} (seeded; not a real Docling "
                        f"conversion). [DEMO]\n",
                    )
                    k.setdefault("processed_at", k.get("ingested_at") or _sd(1))
                else:
                    k.setdefault("processor", None)
                    k.setdefault("normalized_content", None)
                db.add(CustomerKnowledge(customer_id=customer.id, **k))
                stats["knowledge"] += 1
            db.flush()

        # ── Technology dependencies — seed only when the customer has none ──
        # Deterministic, coherent environment topology (PLAN_FEATURE_
        # ENHANCMENTS.md — technology dependency relationships). Resolved by
        # tech NAME against the customer's inventory (seeded above or
        # user-created); unresolvable names are skipped, never fabricated.
        dep_count = (
            db.query(TechnologyDependency)
            .filter(TechnologyDependency.customer_id == customer.id)
            .count()
        )
        if dep_count == 0:
            for d in intel.get("dependencies", []):
                src = (
                    db.query(CustomerTechnology)
                    .filter(
                        CustomerTechnology.customer_id == customer.id,
                        CustomerTechnology.name == d["source"],
                    )
                    .first()
                )
                tgt = (
                    db.query(CustomerTechnology)
                    .filter(
                        CustomerTechnology.customer_id == customer.id,
                        CustomerTechnology.name == d["target"],
                    )
                    .first()
                )
                if src is None or tgt is None or src.id == tgt.id:
                    print(f"  Skipped dependency (missing endpoint): {d['source']} -> {d['target']}")
                    continue
                db.add(
                    TechnologyDependency(
                        customer_id=customer.id,
                        source_id=src.id,
                        target_id=tgt.id,
                        relationship_type=d["type"],
                        verification_state=d.get("verification_state", "verified"),
                        confidence=d.get("confidence"),
                        source_provenance="demo seed (illustrative)",
                        date_observed=d.get("date_observed"),
                    )
                )
                stats["dependencies"] += 1
            db.flush()

    db.commit()
    return stats


def seed_users_and_junctions(db: Session, customer_ids: dict) -> int:
    """Create demo users and assign them to customers via junction table.

    Returns number of junction records created.
    """
    FAKE_HASH = hash_password("seededpass123")

    users = [
        {"username": "acme_ops_admin", "email": "ops@acme.example", "is_admin": 0, "department": "Operations"},
        {"username": "acme_supply_chain", "email": "supply@acme.example", "is_admin": 0, "department": "Supply Chain"},
        {"username": "acme_engineering", "email": "eng@acme.example", "is_admin": 0, "department": "Engineering"},
        {"username": "acme_procurement", "email": "procure@acme.example", "is_admin": 0, "department": "Procurement"},
        {"username": "acme_quality", "email": "quality@acme.example", "is_admin": 0, "department": "Quality"},
        {"username": "acme_hr", "email": "hr@acme.example", "is_admin": 0, "department": "HR / L&D"},
        {"username": "acme_finance", "email": "finance@acme.example", "is_admin": 0, "department": "Finance"},
        {"username": "acme_it", "email": "it@acme.example", "is_admin": 0, "department": "IT"},
        {"username": "gb_finance_lead", "email": "finance@globalbank.example", "is_admin": 0, "department": "Finance"},
        {"username": "gb_it_manager", "email": "it@globalbank.example", "is_admin": 0, "department": "IT"},
        {"username": "gb_risk_analyst", "email": "risk@globalbank.example", "is_admin": 0, "department": "Risk Management", "role": "auditor"},
        {"username": "gb_trading", "email": "trading@globalbank.example", "is_admin": 0, "department": "Trading"},
        {"username": "gb_compliance", "email": "compliance@globalbank.example", "is_admin": 0, "department": "Compliance"},
        {"username": "gb_wealth", "email": "wealth@globalbank.example", "is_admin": 0, "department": "Wealth Management"},
        {"username": "gb_cs_lead", "email": "cs@globalbank.example", "is_admin": 0, "department": "Customer Success"},
        {"username": "techcs_lead", "email": "cs@techcorp.example", "is_admin": 0, "department": "Customer Success"},
        {"username": "tech_ops_mgr", "email": "ops@techcorp.example", "is_admin": 0, "department": "Operations"},
        {"username": "tech_devops", "email": "devops@techcorp.example", "is_admin": 0, "department": "DevOps"},
        {"username": "tech_eng", "email": "eng@techcorp.example", "is_admin": 0, "department": "Engineering"},
        {"username": "tech_hr", "email": "hr@techcorp.example", "is_admin": 0, "department": "HR / L&D"},
        {"username": "health_hr_head", "email": "hr@healthfirst.example", "is_admin": 0, "department": "HR / L&D"},
        {"username": "health_clinical", "email": "clinical@healthfirst.example", "is_admin": 0, "department": "Operations"},
        {"username": "health_compliance", "email": "compliance@healthfirst.example", "is_admin": 0, "department": "Compliance"},
        {"username": "health_patient", "email": "patientcare@healthfirst.example", "is_admin": 0, "department": "Patient Care"},
        {"username": "health_revenue", "email": "revenue@healthfirst.example", "is_admin": 0, "department": "Revenue Cycle"},
        {"username": "retail_ops", "email": "ops@retailmax.example", "is_admin": 0, "department": "Operations"},
        {"username": "retail_cs", "email": "cs@retailmax.example", "is_admin": 0, "department": "Customer Success"},
        {"username": "retail_merch", "email": "merch@retailmax.example", "is_admin": 0, "department": "Merchandising"},
        {"username": "retail_supply", "email": "supply@retailmax.example", "is_admin": 0, "department": "Supply Chain"},
        {"username": "retail_hr", "email": "hr@retailmax.example", "is_admin": 0, "department": "HR / L&D"},
        {"username": "retail_finance", "email": "finance@retailmax.example", "is_admin": 0, "department": "Finance"},
        {"username": "retail_security", "email": "security@retailmax.example", "is_admin": 0, "department": "Loss Prevention"},
    ]

    junctions = [
        ("acme_ops_admin", "Acme Manufacturing", "owner"),
        ("acme_supply_chain", "Acme Manufacturing", "owner"),
        ("acme_engineering", "Acme Manufacturing", "owner"),
        ("acme_procurement", "Acme Manufacturing", "owner"),
        ("acme_quality", "Acme Manufacturing", "owner"),
        ("acme_hr", "Acme Manufacturing", "member"),
        ("acme_finance", "Acme Manufacturing", "member"),
        ("acme_it", "Acme Manufacturing", "member"),
        ("gb_finance_lead", "GlobalBank Financial Services", "owner"),
        ("gb_it_manager", "GlobalBank Financial Services", "owner"),
        ("gb_risk_analyst", "GlobalBank Financial Services", "auditor"),
        ("gb_trading", "GlobalBank Financial Services", "member"),
        ("gb_compliance", "GlobalBank Financial Services", "member"),
        ("gb_wealth", "GlobalBank Financial Services", "member"),
        ("gb_cs_lead", "GlobalBank Financial Services", "member"),
        ("techcs_lead", "TechCorp Solutions", "owner"),
        ("tech_ops_mgr", "TechCorp Solutions", "owner"),
        ("tech_devops", "TechCorp Solutions", "owner"),
        ("tech_eng", "TechCorp Solutions", "owner"),
        ("tech_hr", "TechCorp Solutions", "member"),
        ("health_hr_head", "HealthFirst Medical Group", "owner"),
        ("health_clinical", "HealthFirst Medical Group", "owner"),
        ("health_compliance", "HealthFirst Medical Group", "owner"),
        ("health_patient", "HealthFirst Medical Group", "member"),
        ("health_revenue", "HealthFirst Medical Group", "member"),
        ("retail_ops", "RetailMax", "owner"),
        ("retail_cs", "RetailMax", "owner"),
        ("retail_merch", "RetailMax", "member"),
        ("retail_supply", "RetailMax", "member"),
        ("retail_hr", "RetailMax", "member"),
        ("retail_finance", "RetailMax", "member"),
        ("retail_security", "RetailMax", "member"),
    ]

    created = 0

    for u_data in users:
        existing = db.query(User).filter(User.username == u_data["username"]).first()
        if existing:
            continue
        user = User(
            username=u_data["username"],
            email=u_data["email"],
            hashed_password=FAKE_HASH,
            department=u_data.get("department"),
            role=u_data.get("role", "user"),
            is_admin=u_data.get("is_admin", 0),
            approved=1,
            is_active=1,
        )
        db.add(user)
        db.flush()
        created += 1
        print(f"  Created user: {u_data['username']}")

    for username, customer_name, role in junctions:
        user = db.query(User).filter(User.username == username).first()
        customer = db.query(Customer).filter(Customer.name == customer_name).first()
        if not user or not customer:
            continue
        existing = db.query(CustomerUser).filter_by(user_id=user.id, customer_id=customer.id).first()
        if existing:
            continue
        cu = CustomerUser(
            customer_id=customer.id,
            user_id=user.id,
            role=role,
            granted_by=user.id,
            granted_at=datetime.now(UTC),
        )
        db.add(cu)
        db.flush()
        print(f"  Assigned {username} as {role} on {customer_name}")
        created += 1

    db.commit()
    return created


# ── Customer CSV import ──────────────────────────────────────────────────────
# Separate from the demo seed (seed_database / CUSTOMERS): imports your own
# customer list with only the customer name + branch + a name-only pending
# Customer Owner (the sales rep). Every other customer area stays NULL until
# filled in the app (users.email is nullable for pending rows).
#
# Idempotent: re-running creates no duplicate customers, branches, users, or
# junction rows (matched by name / username / (customer_id,user_id)).
#
# CSV columns: customer_name, rep_name, branch (all optional except
# customer_name). Rep name is used as the owner's display_name; the username
# is the ASCII slug. A NULL rep_name -> a placeholder owner
# "seed_customer_<slug>" to fill out later.


# Seed-scope exclusion: funding-vehicle rows (rebate / marketing-funds
# accounts) are not customer relationships and are skipped on import.
_EXCLUDED_CUSTOMER_NAME = re.compile(
    r"rebates only|marketing funds?|m[a-z]+eting funds",
    re.IGNORECASE,
)


def is_excluded_seed_customer(name: str) -> bool:
    """True if the customer name is out of seed scope (rebate/marketing-funds)."""
    return bool(_EXCLUDED_CUSTOMER_NAME.search(str(name or "")))


def _slugify(name: str) -> str:
    """Deterministic ASCII slug for a username (max 100 chars, non-empty)."""
    import re
    import unicodedata
    s = unicodedata.normalize("NFKD", str(name))
    s = s.encode("ascii", "ignore").decode("ascii").lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    if len(s) > 100:
        s = s[:100].rstrip("-")
    return s or "unnamed"


def email_prefix(email: str) -> str:
    """Extract the part before @ and lowercase it, without hyphen insertion.

    Used for the username = email-prefix rule (charter A1).
    admin is the named exception — never apply this rule to it.
    """
    if not email or not isinstance(email, str):
        return ""
    prefix = email.split("@")[0]
    import unicodedata
    s = unicodedata.normalize("NFKD", prefix)
    s = s.encode("ascii", "ignore").decode("ascii").lower()
    return s or ""

def _get_or_create_branch(db: Session, branch: str):
    row = db.query(Branch).filter(Branch.name == branch).first()
    if row is None:
        row = Branch(name=branch)
        db.add(row)
        db.flush()
    return row


def _get_or_create_pending_owner(
    db: Session,
    display_name: str,
    username: str,
    department: str | None = None,
):
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        user = User(
            username=username,
            email=None,  # pending: operator fills contact details later
            display_name=display_name,
            department=department,
            role="user",
            is_admin=0,
            approved=0,  # pending approval
            is_active=0,  # pending: cannot authenticate until filled out
            auth_provider="local",
        )
        db.add(user)
        db.flush()
    return user


def seed_customers_from_csv(db: Session, csv_path: str) -> dict:
    """Seed real customers + name-only pending owners from the canonical CSV.

    Returns a summary dict {customers, branches, owners, junctions,
    customers_created, owners_created}.
    """
    import csv as _csv

    with open(csv_path, newline="") as fh:
        reader = _csv.DictReader(fh)
        rows = [
            r for r in reader
            if not is_excluded_seed_customer(r.get("customer_name") or "")
        ]

    created_customers = 0
    created_owners = 0
    created_junctions = 0
    created_branches = 0

    # 1. Branch reference table (distinct, first-seen order).
    for r in rows:
        b = (r.get("branch") or "").strip()
        if not b:
            continue
        if db.query(Branch).filter(Branch.name == b).first() is None:
            _get_or_create_branch(db, b)
            created_branches += 1
    db.flush()

    # 2. Customers + owner users + owner junctions.
    for r in rows:
        name = (r.get("customer_name") or "").strip()
        if not name:
            continue
        branch = (r.get("branch") or "").strip() or None
        rep = (r.get("rep_name") or "").strip() or None

        customer = db.query(Customer).filter(Customer.name == name).first()
        if customer is None:
            customer = Customer(name=name, branch=branch)
            db.add(customer)
            db.flush()
            created_customers += 1
        elif branch and customer.branch != branch:
            # Backfill a branch that was present in the CSV but missing on a
            # pre-existing customer (idempotent, only fills empties/stale).
            customer.branch = branch

        if rep:
            owner_display = rep
            owner_username = _slugify(rep)
        else:
            owner_display = name
            owner_username = f"seed_customer_{_slugify(name)}"

        owner = db.query(User).filter(User.username == owner_username).first()
        if owner is None:
            # Named rep owners are the primary (outside) reps of the sales
            # org -> department "Sales". Placeholder owners (no rep name)
            # stay department-less for the operator to assign.
            owner = _get_or_create_pending_owner(
                db,
                owner_display,
                owner_username,
                department="Sales" if rep else None,
            )
            created_owners += 1
        elif owner.display_name != owner_display:
            owner.display_name = owner_display

        existing_j = (
            db.query(CustomerUser)
            .filter(
                CustomerUser.customer_id == customer.id,
                CustomerUser.user_id == owner.id,
            )
            .first()
        )
        if existing_j is None:
            db.add(CustomerUser(
                customer_id=customer.id,
                user_id=owner.id,
                role="owner",
                granted_by=owner.id,
                granted_at=datetime.now(UTC),
            ))
            created_junctions += 1

    db.commit()
    return {
        "customers": db.query(Customer).count(),
        "branches": db.query(Branch).count(),
        "owners": created_owners,
        "junctions": created_junctions,
        "customers_created": created_customers,
        "owners_created": created_owners,
        "junctions_created": created_junctions,
        "branches_created": created_branches,
    }


def export_to_json(path: str) -> None:
    """Export all use cases to a JSON file for documentation/testing."""
    db = get_session()
    try:
        use_cases = db.query(UseCase).all()
        data = [uc.to_dict() for uc in use_cases]
        Path(path).write_text(json.dumps(data, indent=2, default=str))
        print(f"\nExported {len(data)} use case(s) to {path}")
    finally:
        db.close()


# Initial global admin user (fresh databases).
GLOBAL_ADMIN_USERNAME = "admin"
GLOBAL_ADMIN_EMAIL = "admin@sail.example"
GLOBAL_ADMIN_DISPLAY = "Administrator"


def _bootstrap_admin(db: Session) -> None:
    """Create the default admin account on a fresh database.

    The deployment runs this explicitly after migrations. Existing users,
    including their passwords, are never modified.
    """
    if db.query(User).count() == 0:
        admin = User(
            username=GLOBAL_ADMIN_USERNAME,
            email=GLOBAL_ADMIN_EMAIL,
            hashed_password=hash_password("adm" "in"),
            display_name=GLOBAL_ADMIN_DISPLAY,
            department="Global Administrator",
            is_admin=1,
            approved=1,
            is_active=1,
        )
        db.add(admin)
        db.commit()
        print("  Created default admin user (admin / admin)")


def reconcile_legacy_admin_identity(db: Session) -> bool:
    """Bring an existing volume's bootstrap admin to the 2026-10-14 identity.

    The operator directive names the global admin user as username
    ``admin`` / display ``Administrator`` / email ``admin@sail.example``.
    Fresh databases already match (see ``_bootstrap_admin``); this
    reconcile updates the ORIGINAL admin row on live volumes in place
    (the username is preserved — it is a stable identifier; only the email
    and display name are brought to the directed values). Fills-only: it
    never creates, deactivates, or re-hashes anything. Idempotent.
    """
    changed = False
    admin = (
        db.query(User)
        .filter(User.is_admin == 1, User.username == GLOBAL_ADMIN_USERNAME)
        .first()
    )
    if admin is None:
        # Fall back to the first global admin row on volumes where the
        # username drifted; still fills-only (no new rows).
        admin = db.query(User).filter(User.is_admin == 1).first()
    if admin is None:
        return False
    if admin.email != GLOBAL_ADMIN_EMAIL:
        admin.email = GLOBAL_ADMIN_EMAIL
        changed = True
    if (admin.display_name or "") != GLOBAL_ADMIN_DISPLAY:
        admin.display_name = GLOBAL_ADMIN_DISPLAY
        changed = True
    if changed:
        db.commit()
        print(f"  Admin identity reconciled: {admin.username} <{admin.email}>")
    return changed


def main():
    parser = argparse.ArgumentParser(description="Seed S-A-I-L (Sales Analytics and Intelligence Launchpad) with sample data")
    parser.add_argument("--reset", action="store_true", help="Delete all existing use cases before seeding")
    parser.add_argument("--admin-only", action="store_true", help="Create the initial admin only if there are no users")
    parser.add_argument("--json", dest="json_path", type=str, default=None, help="Export seeded data to JSON file")
    # Import your own customers instead of the demo data: a CSV with columns
    # customer_name (required), rep_name, branch. Only customers, branches and
    # name-only pending owners are created; the demo seed is skipped.
    parser.add_argument("--csv", dest="csv_path", type=str, default=None,
                        help="Seed customers + branches + pending owners from your own "
                             "CSV (customer_name,rep_name,branch).")
    args = parser.parse_args()

    print("S-A-I-L (Sales Analytics and Intelligence Launchpad) — Sample Data Seeder")
    print("=" * 40)
    print()

    db = get_session()
    _bootstrap_admin(db)
    if args.admin_only:
        db.close()
        return

    csv_path = args.csv_path

    if csv_path is not None:
        print(f"  Seeding customers from: {csv_path}")
        summary = seed_customers_from_csv(db, csv_path)
        print("\nDone (customer CSV import).")
        print(f"  Customers total: {summary['customers']} ({summary['customers_created']} new)")
        print(f"  Branches total:  {summary['branches']} ({summary['branches_created']} new)")
        print(f"  Owner users new: {summary['owners_created']}")
        print(f"  Owner junctions new: {summary['junctions_created']}")
        db.close()
        return

    try:
        created = seed_database(db, reset=args.reset)

        # S-A-I-L P7 — deterministic demo customer intelligence (tech inventory +
        # sales notes). Non-destructive: only fills customers that have no
        # existing technology/note records; --reset clears the S-A-I-L tables first.
        seed_customer_intelligence(db, reset=args.reset)

        if args.reset:
            users_created = seed_users_and_junctions(db, {})
            print(f"\n  Created {users_created} user/junction records for multi-tenant demo")

        total = db.query(UseCase).count()
        print()
        print(f"Done. {total} total use case(s) in database ({created} new, {total - created} existing).")

        customers = db.query(Customer).count()
        departments = db.query(Department).count()
        scored = db.query(UseCase).filter(UseCase.overall_score.isnot(None)).count()
        avg_score = db.query(UseCase).with_entities(UseCase.overall_score).filter(
            UseCase.overall_score.isnot(None)
        ).all()

        print(f"  Customers: {customers}")
        print(f"  Departments: {departments}")
        tech_total = db.query(CustomerTechnology).count()
        notes_total = db.query(SalesNote).count()
        kn_total = db.query(CustomerKnowledge).count()
        print(f"  Technology items: {tech_total}")
        print(f"  Sales notes: {notes_total}")
        print(f"  Knowledge sources: {kn_total}")
        print(f"  Technology dependencies: {db.query(TechnologyDependency).count()}")
        print(f"  Scored: {scored}/{total}")
        if avg_score:
            scores = [s[0] for s in avg_score if s[0] is not None]
            if scores:
                print(f"  Average score: {sum(scores)/len(scores):.1f}")
                print(f"  Score range: {min(scores):.1f} — {max(scores):.1f}")

    finally:
        db.close()

    if args.json_path:
        export_to_json(args.json_path)


if __name__ == "__main__":
    main()
