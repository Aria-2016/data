# Import necessary libraries  20241202 17:00
import asyncio  # Asynchronous programming support
import re  # Regular expression library for text matching
import subprocess  # For executing system commands, such as running Python scripts
from contextvars import Context
from datetime import datetime
from dotenv import get_key
import openpyxl

import os
# Import related modules from the MetaGPT framework
import fire  # Command-line interface tool for quickly creating command-line interfaces
from metagpt.actions import Action, UserRequirement  # Base class for defining actions
from metagpt.logs import logger  # Logging module
from metagpt.roles.role import Role, RoleReactMode  # Role base class and reaction mode
from metagpt.schema import Message  # Class defining message structure
import typer
from metagpt.environment import Environment
from typing import Dict, Any
import pandas as pd
from typing import List

from pymupdf import message

from typing import Dict, Optional
from asyncio import Lock
from eu_data_english import countrys_EU
from typing import ClassVar
import json
# Create environment

env = Environment(desc="Simulation game of EU voting on imposing additional tariffs on Chinese electric vehicles")
vote_result_round = {}
vote_round_number = 3

import warnings
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from metagpt.actions import UserRequirement
from metagpt.const import MESSAGE_ROUTE_TO_ALL, SERDESER_PATH
from metagpt.context import Context
from metagpt.environment import Environment
from metagpt.logs import logger
from metagpt.roles import Role
from metagpt.schema import Message
from metagpt.config2 import Config
from metagpt.utils.common import (
    NoMoneyException,
    read_json_file,
    serialize_decorator,
    write_json_file,
)
# Below are some example configurations
llm_secretary = Config.from_home("config2.Qianwen.yaml")  # Load custom configuration from `~/.metagpt` directory

class Team(BaseModel):
    """
    Team: Possesses one or more roles (agents), SOP (Standard Operating Procedures), and an environment for instant messaging,
    dedicated to any multi-agent activity, such as collaboratively writing executable code.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)
    env: Optional[Environment] = None
    investment: float = Field(default=10.0)
    idea: str = Field(default="")

    def __init__(self, context: Context = None, **data: Any):
        super(Team, self).__init__(**data)
        ctx = context or Context()
        if not self.env:
            self.env = Environment(context=ctx)
        else:
            self.env.context = ctx  # The `env` object is allocated by deserialization
        if "roles" in data:
            self.hire(data["roles"])
        if "env_desc" in data:
            self.env.desc = data["env_desc"]

    def serialize(self, stg_path: Path = None):
        stg_path = SERDESER_PATH.joinpath("team") if stg_path is None else stg_path
        team_info_path = stg_path.joinpath("team.json")

        # Ensure the directory exists
        stg_path.mkdir(parents=True, exist_ok=True)

        # Write the JSON file with UTF-8 encoding
        with open(team_info_path, 'w', encoding='utf-8') as f:
            json.dump(self.model_dump(), f, ensure_ascii=False, indent=4)

    @classmethod
    def deserialize(cls, stg_path: Path, context: Context = None) -> "Team":
        """stg_path = ./storage/team"""
        # Recover team_info
        team_info_path = stg_path.joinpath("team.json")
        if not team_info_path.exists():
            raise FileNotFoundError(
                "Recover storage meta file `team.json` does not exist, " "not to recover and please start a new project."
            )

        team_info: dict = read_json_file(team_info_path)
        ctx = context or Context()
        team = Team(**team_info, context=ctx)
        return team

    def hire(self, roles: list[Role]):
        """Hire roles to cooperate"""
        self.env.add_roles(roles)

    @property
    def cost_manager(self):
        """Get cost manager"""
        return self.env.context.cost_manager

    def invest(self, investment: float):
        """Invest company. raise NoMoneyException when exceed max_budget."""
        self.investment = investment
        self.cost_manager.max_budget = investment
        logger.info(f"Investment: ${investment}.")

    def _check_balance(self):
        if self.cost_manager.total_cost >= self.cost_manager.max_budget:
            raise NoMoneyException(self.cost_manager.total_cost, f"Insufficient funds: {self.cost_manager.max_budget}")

    def run_project(self, idea, send_to: str = ""):
        """Run a project from publishing user requirement."""
        self.idea = idea

        # Human requirement.
        self.env.publish_message(
            Message(role="Human", content=idea, cause_by=UserRequirement, send_to=send_to or MESSAGE_ROUTE_TO_ALL),
            peekable=False,
        )

    def start_project(self, idea, send_to: str = ""):
        """
        Deprecated: This method will be removed in the future.
        Please use the `run_project` method instead.
        """
        warnings.warn(
            "The 'start_project' method is deprecated and will be removed in the future. "
            "Please use the 'run_project' method instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.run_project(idea=idea, send_to=send_to)

    def _save(self):
        logger.info(self.model_dump_json())

    @serialize_decorator
    async def run(self, n_round=3, idea="", send_to="", auto_archive=True):
        """Run company until target round or no money"""
        if idea:
            self.run_project(idea=idea, send_to=send_to)
        global vote_round_number

        while n_round > 0:
            # self._save()
            vote_round_number = n_round
            print(f"n_round in team is {n_round}")
            print(f"vote_round_number in team is {vote_round_number}")
            n_round -= 1
            logger.debug(f"max {n_round=} left.")
            self._check_balance()
            await self.env.run()
        self.env.archive(auto_archive)

        return self.env.history

def parse_answer(rsp):
    pattern = r"```plaintext(.*)```"
    match = re.search(pattern, rsp, re.DOTALL | re.MULTILINE)
    code_answer = match.group(1).strip() if match else rsp
    return code_answer

# Calculate whether the vote passes
def determine_vote_pass(countrys_EU):
    # Read Excel file
    df = pd.read_excel('vote_results.xlsx')
    # Check if 'Country' column exists
    if 'Country' not in df.columns:
        print("DataFrame does not contain 'Country' column.")
        return  # Or handle the case of missing columns
    # Get country names and the last column's voting results
    countries = df['Country'].tolist()
    vote_column = df.iloc[:, -1]  # Get the last column
    voting_results = dict(zip(countries, vote_column))

    # Calculate total votes and total population
    total_votes = len(voting_results)
    total_population = sum(countrys_EU[country].get("population", 0) for country in voting_results)

    # Calculate against votes and against population
    against_votes = 0
    against_population = 0
    for country, result in voting_results.items():
        population = countrys_EU.get(country, {}).get("population", 0)
        if result == "Against":
            against_votes += 1
            against_population += population

    # Determine if the veto condition is met
    if (against_votes / total_votes) > 2 / 3 and (against_population / total_population) > 0.65:
        final_result = "Final voting result: The proposal to impose an additional 25% tariff on Chinese electric vehicles was not passed."
    else:
        final_result = "Final voting result: The proposal to impose an additional 25% tariff on Chinese electric vehicles was passed."

    # Update each country's final_voting_results
    for country in countrys_EU:
        countrys_EU[country]["final_voting_results"] = final_result

def extract_voting_results(text: str):
    # Extract detailed voting information from the text
    detailed_info_start = text.find('Detailed voting information:') + len('Detailed voting information:')
    detailed_info = text[detailed_info_start:]

    # Split the detailed info by semicolon to get individual country results
    country_results = detailed_info.split(';')[:-1]  # Exclude the last empty string after split
    # Create a dictionary to store the voting results
    voting_results = {}

    for result in country_results:
        # Split each result by '，' to separate country name and voting result
        parts = result.split('，')
        country_name = parts[0].split('：')[1].strip()  # Get the country name after "Country Name：" and remove any leading/trailing spaces
        vote_result = parts[1].split('：')[1].strip()  # Get the vote result after "Vote Result：" and remove any leading/trailing spaces
        voting_results[country_name] = vote_result
    print(voting_results)
    return voting_results

class Vote(Team):
    name: str
    disc: str

    def hello(self):
        print(f"Country class {self.name} instantiated successfully")

class StartToVote(Action):
    name: str = "StartToVote_action"
    profile: str = "Send a message to all EU member states to start voting"

    async def run(self, msg: Message):
        all_countries = list(countrys_EU.keys())
        for task_country in all_countries:
            msg = Message(content="Start voting", cause_by=StartToVote, send_to=task_country)
            print(f"StartToVote's task_country is {msg.send_to}, task completed")
            env.publish_message(msg)

        msg = Message(content="Start voting", cause_by=StartToVote, send_to="China")
        env.publish_message(msg)
        return msg

class VoteRecordAction(Action):
    name: str = "VoteRecordAction"
    profile: str = "Action to record the voting results of all EU member states"

    # Use class variables to store voting results
    votes: ClassVar[Dict[str, Dict[int, str]]] = {}
    lock: ClassVar[Lock] = Lock()  # For thread safety

    async def run(self, msg: Message, simu_round_number: int):
        global vote_round_number
        # If merging results from each round is needed, then record_round_number = simu_round_number. If recording results within each round is needed, then record_round_number = simu_round_number * 100 + vote_round_number
        record_round_number = simu_round_number
        country_name = msg.sent_from
        content = msg.content
        # Parse content to determine if it's agree, against, or abstain
        vote = self.parse_vote(content)
        if vote is None:
            print(f"Cannot parse {country_name}'s voting content: {content}")
            return

        print(f"VoteRecordAction received message from {country_name}, content: {content}, parsed vote content: {vote}")

        # Get the current country's voting record
        if country_name not in self.votes:
            self.votes[country_name] = {}

        # Record the current round's voting result
        self.votes[country_name][record_round_number] = vote
        print(f"VoteRecordAction recorded vote content: {self.votes}")

        # Update vote_info_of_other_countries in countrys_EU
        countrys_EU[country_name]["vote_info_of_home_country"] = vote
        for country in countrys_EU:
            if country != country_name:
                existing_info = countrys_EU[country]['vote_info_of_other_countries']
                # Parse the existing info into a dictionary
                vote_info_dict = self.parse_vote_info(existing_info)
                # Update or add the new vote
                vote_info_dict[country_name] = vote
                # Reconstruct the string
                updated_info = self.construct_vote_info(vote_info_dict)
                # Update the country's vote_info_of_other_countries
                countrys_EU[country]['vote_info_of_other_countries'] = updated_info

        # Write to Excel file
        async with self.lock:
            await self.write_to_excel()

    def parse_vote_info(self, vote_info_str: str):
        vote_info_dict = {}
        if vote_info_str:
            pairs = vote_info_str.split(', ')
            for pair in pairs:
                parts = pair.split(': ')
                if len(parts) == 2:
                    country, vote = parts
                    vote_info_dict[country.strip()] = vote.strip()
        return vote_info_dict

    def construct_vote_info(self, vote_info_dict: dict):
        pairs = [f"{country}: {vote}" for country, vote in vote_info_dict.items()]
        return ', '.join(pairs)

    def parse_vote(self, content: str) -> Optional[str]:
        # Determine if the content is agree, against, or abstain
        if "Agree" in content:
            return "Agree"
        elif "Support" in content:
            return "Agree"
        elif "Against" in content:
            return "Against"
        elif "Abstain" in content:
            return "Abstain"
        else:
            return None

    async def write_to_excel(self):
        # Write the votes dictionary to an Excel file
        df = pd.DataFrame(self.votes)
        df = df.transpose()
        df.reset_index(inplace=True)
        df.rename(columns={'index': 'Country'}, inplace=True)
        print(f"VoteRecordAction starts writing to file")

        # Get all round numbers
        round_numbers = sorted(set([rn for country_votes in self.votes.values() for rn in country_votes.keys()]))

        # Create a dictionary to store data
        data = {'Country': []}
        for rn in round_numbers:
            data[rn] = []

        # Fill data
        for country, votes in self.votes.items():
            data['Country'].append(country)
            for rn in round_numbers:
                data[rn].append(votes.get(rn, ''))

        # Create DataFrame
        df = pd.DataFrame(data)

        # Save to Excel file
        df.to_excel('vote_results.xlsx', index=False)

class DecideCommunication(Action):
    PROMPT_TEMPLATE: str = """
    # Role
    - **Country Name**: {country_name}
    - **Main Task**: Based on current information and situation, decide which other countries to communicate with to reach a consensus on whether to support a 25% tariff on Chinese electric vehicles.

    # Background Information
    - **Government Interests Dimension**: {government_interests}
    - **Diplomatic and International Relations Dimension**: {diplomatic_Relations}
    - **Domestic Economic Pressures Dimension**: {domestic_Economic_Pressures}
    - **Political and Public Opinion Dimension**: {political_and_Public_Opinion}
    - **Historical and Cultural Background Dimension**: {historical_and_Cultural_Background}
    - **China's Feedback and Communication with Other Countries**: {china_feedback_and_communication}
    - **Contextual Information**: {context}
    - **Relations with the EU**: {european_relations}
    - **List of Candidate Countries for Communication within the EU**: {countrys_name_str}
    - **Final Voting Results and Voting Information of Other Countries**: {vote_info_of_other_countries}
    # Workflow/Tasks
    1. **Analyze Current Situation**: Consider the country's economic status, trade relations with China, and the positions of other countries in the previous round of voting. Achieve goals through appropriate interest exchanges.
    2. **Communication Objectives**: Based on the analysis, select countries whose voting results can be influenced by the country. If the country abstains, no country needs to be selected. If the country has limited influence, no country needs to be selected.
    3. **Determine Communication Countries**: From the list of candidate countries for communication within the EU, select no more than 4 country names.

    # Output Example
    - **List of Communication Countries**: r"```plaintext country_name,country_name,country_name``` with NO other texts. Ensure the format is correct, no extra line breaks, and country names are in English.
    """

    PROMPT_TEMPLATE_COMMUNICATION: str = """
    # Communication Between Home Country and Target Country
    - **Home Country Name**: {home_country_name}
    - **Target Country Name**: {target_country_name}
    - **Home Country Government Interests Dimension**: {government_interests}
    - **Diplomatic and International Relations Dimension**: {diplomatic_Relations}
    - **Domestic Economic Pressures Dimension**: {domestic_Economic_Pressures}
    - **Political and Public Opinion Dimension**: {political_and_Public_Opinion}
    - **Historical and Cultural Background Dimension**: {historical_and_Cultural_Background}
    - **Relations with the EU**: {european_relations}
    - **Target Country Government Interests Dimension**: {target_country_government_interests}
    - **China's Feedback and Communication with Other Countries**: {china_feedback_and_communication}
    - **Previous Round Voting Information of Other Countries**: {vote_info_of_other_countries}
    - **Previous Round Final Results**: {final_voting_results}
    - **Home Country Preliminary Voting Information**: {vote_info_of_home_country}
    - **Contextual Information**: {context}
    # Communication Strategy
    1. **Analyze Positions**: Based on the final voting results and voting information of other countries, determine if the final voting result aligns with the home country's voting intention. Compare the positions of the home country and the target country, analyzing commonalities and differences on the issue of electric vehicle tariffs.
    2. **Unify Positions**: Compare the home country's industrial status and trade data with China, as well as views on the Chinese electric vehicle market, to coordinate positions and hope that the target country's vote aligns with the home country's preliminary voting intention.
    3. **Coordinate Positions**: If there are differences, weigh the pros and cons and attempt to exchange interests. If the home country's preliminary intention is to agree, hope that the target country agrees or abstains. If the home country's preliminary intention is to oppose, hope that the target country opposes or abstains. If the home country abstains, no specific communication action is needed.
    4. **Basic Principles**: Only powerful countries can promise to offer interests to other countries to change their voting intentions. Communication content must be realistic. Economically weaker countries cannot offer interests to economically stronger countries. Interests are only offered when tariffs on Chinese electric vehicles or China's countermeasures significantly impact the home country's interests.
    5. **Exchange Information**: Weigh the pros and cons. If the country is strong and economically well-off, it can make vote-pulling promises or exchange interests. Hope that the target country's vote aligns with the home country's preliminary voting intention. For example, support within the EU budget, transfer of certain advantageous industries, etc. Content should be concise, no more than 50 words, and 
    # Output Example
    - **Communication Exchange**: r"```plaintext Home Country Name sends communication message to Target Country Name, hoping for a specific vote, communication content``` with NO other texts. Ensure the format is correct.
    """


    name: str = "DecideCommunication"
    profile: str = ("Choose whether to communicate with other EU countries and specify which countries to engage with, "
                    "then send messages to other EU countries to propose agreements or positions on the tariff issue.")


    async def run(self, msg: Message, country: Dict[str, Any], simu_round_number: int):
        context_decide_communication = msg.content
        country_name = country["country_name"]
        government_interests = country["government_interests"]
        diplomatic_relations = country["diplomatic_Relations"]
        domestic_economic_pressures = country["domestic_Economic_Pressures"]
        political_and_public_opinion = country["political_and_Public_Opinion"]
        historical_and_cultural_background = country["historical_and_Cultural_Background"]
        china_feedback_and_communication = country["china_feedback_and_communication"]
        european_relations = country["european_relations"]
        vote_info_of_home_country = country["vote_info_of_home_country"]
        vote_info_of_other_countries = country["vote_info_of_other_countries"]
        final_voting_results = country["final_voting_results"]
        countrys_name = list(countrys_EU.keys())
        countrys_name_str = ' '.join(countrys_name)
        # print(f"DecideCommunication countrys_name: {countrys_name}, message from {msg.sent_from}")
        prompt = self.PROMPT_TEMPLATE.format(country_name=country_name, context=context_decide_communication,
                                             government_interests=government_interests,
                                             diplomatic_Relations=diplomatic_relations,
                                             vote_info_of_other_countries=vote_info_of_other_countries,
                                             final_voting_results=final_voting_results,
                                             vote_info_of_home_country=vote_info_of_home_country,
                                             domestic_Economic_Pressures=domestic_economic_pressures,
                                             political_and_Public_Opinion=political_and_public_opinion,
                                             historical_and_Cultural_Background=historical_and_cultural_background,
                                             china_feedback_and_communication=china_feedback_and_communication,
                                             european_relations=european_relations,
                                             countrys_name_str=countrys_name_str)

        # print(f"Input message content for DecideCommunication: {context_decide_communication}, message from {msg.sent_from}, DecideCommunication task started")
        # If it's the last round, no communication is needed
        global vote_round_number
        rsp = ""
        if vote_round_number > 1:
            rsp = await self._aask(prompt)
            await asyncio.sleep(10)
        answer = parse_answer(rsp)
        print(
            f"DecideCommunication decision result: {answer}, message from {msg.sent_from}, DecideCommunication task completed")

        # Parse the answer to determine the list of countries to communicate with
        communication_countries = answer.split(",")
        # print(f"##### Pre-filtered list of countries to communicate with in DecideCommunication: {communication_countries}, message from {msg.sent_from}")
        # Filter out actual country names
        communication_countries = [name for name in communication_countries if name in countrys_name]
        print(
            f"##### Post-filtered list of countries to communicate with in DecideCommunication: {communication_countries}, message from {msg.sent_from}")
        communication_context = []
        for target_country_name in communication_countries:
            # print(f"+++++++++++++++++++++++++ Country to communicate with: {target_country_name}, +++++++++++++++++++++")
            target_country_name = target_country_name.strip()
            home_country_name = country_name
            home_country = countrys_EU[home_country_name]
            target_country = countrys_EU[target_country_name]
            prompt = self.PROMPT_TEMPLATE_COMMUNICATION.format(
                home_country_name=home_country_name,
                target_country_name=target_country_name,
                government_interests=home_country["government_interests"],
                diplomatic_Relations=home_country["diplomatic_Relations"],
                domestic_Economic_Pressures=home_country["domestic_Economic_Pressures"],
                political_and_Public_Opinion=home_country["political_and_Public_Opinion"],
                historical_and_Cultural_Background=home_country["historical_and_Cultural_Background"],
                european_relations=home_country["european_relations"],
                china_feedback_and_communication=home_country["china_feedback_and_communication"],
                target_country_government_interests = target_country["government_interests"],
                vote_info_of_other_countries = home_country["vote_info_of_other_countries"],
                vote_info_of_home_country = home_country["vote_info_of_home_country"],
                final_voting_results = home_country["final_voting_results"],
                context = context_decide_communication
            )

            # print(f"Input message content for DecideCommunication: {msg.content}, message from {msg.sent_from}, starting communication with {target_country_name}")
            rsp = await self._aask(prompt)
            await asyncio.sleep(10)
            answer = parse_answer(rsp)
            msg = Message(content=answer, cause_by="DecideCommunication",
                          sent_from=home_country_name, send_to=f"Secretary_{target_country_name}")
            env.publish_message(msg)
            # Write the answer content to a file
            # Get the current system time
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # Specify the file name and path, file is in the current directory
            file_name = "communication_info.txt"
            file_text = "Home country: " + home_country_name + "; Target country: " + target_country_name + "; Communication content: " + answer
            # Open the file in append mode
            with open(file_name, 'a', encoding='utf-8') as file:
            # Write the string and time, then add a newline
                file.write(f"{file_text}, time: {current_time}\n")
            # communication_context.append(answer)
            print(
                f"Message content: {msg}, EuCountry {home_country_name} {self.name} publish_message task completed, sent to {target_country_name}.")
            # confirmed_communication_countries = ' '.join(communication_countries)
            # print(f"DecideCommunication final decision result: {communication_context}, message from {msg.sent_from}, DecideCommunication task completed")

            return Message(content=answer, cause_by=self.name, sent_from=country["country_name"])


class MakeConclusion(Action):
    PROMPT_TEMPLATE: str = """
    # Role
        - **Country Name**: {country_name}
        - **Main Task**: Based on the country's interests, feedback from the country's secretary, and communication results with other countries and China, decide whether to agree to impose an additional 25% tariff on Chinese electric vehicles and indicate the position in the EU vote.
        - **Main Objective**: Through voting decisions, aim to enhance the competitiveness of the country's electric vehicle industry, promote economic growth, ensure employment, and maintain the country's influence within the EU while maximizing benefits.

    # Contextual Information
        - The European Commission released a report on Chinese electric vehicles: "Sufficient evidence has been collected to indicate that recent large-scale imports of low-priced and subsidized Chinese electric vehicles into the EU pose an economic threat to the EU's electric vehicle industry."
                      The European Commission believes: "The EU's stance towards China is becoming increasingly tough. The EU views China as a potential partner in certain areas but also as a competitor and systemic rival. The EU urgently needs to prevent the EU's electric vehicle industry from suffering a fate similar to that of China's solar panel industry, avoiding being impacted by cheap Chinese electric vehicles to protect the local automotive market. While consumers may benefit from cheaper Chinese cars in the short term, allowing unfair practices may ultimately lead to reduced competition and higher prices in the long term."
        - **Contextual information, including the country's secretary's information and key communication information with other EU countries**: {context}
        - **Previous round EU voting results**: {final_voting_results}


    # China's Feedback Information  
        - **China's Feedback**: {china_feedback_and_communication}

    # Background Information

        - **National Interests Dimension**: {government_interests}
        - **Foreign Trade and International Relations with China Dimension**: {diplomatic_Relations}
        - **Historical and Cultural Background Dimension**: {historical_and_Cultural_Background}
        - **Political and Public Opinion Dimension**: {political_and_Public_Opinion}
        - **Domestic Economic Pressures Dimension**: {domestic_Economic_Pressures}
        - **Relations with the EU Dimension**: {european_relations}

    # Thought Process:
        1. Analyze contextual information:
            Focus on the European Commission's report on Chinese electric vehicles, domestic industry reactions (Domestic Industry Reactions Affected by China's Countermeasures), and the European Commission's (Communication from European Commission) views and recommendations.
            Evaluate communication with other EU countries (Communication from other EU countries), looking for reasons to support or oppose.
        2. Consider previous round voting results:
            Refer to the previous round voting results to see which countries supported or opposed.
            Analyze whether these countries' positions will influence the country's decision.
        3. Evaluate China's feedback:
            Assess the potential impact of China's feedback on the country.
            Consider whether to adjust the position to avoid conflict with China.
        4. Weigh national interests:
            Assess the impact on the country's automotive industry if Chinese electric vehicles dominate the EU market.
            Consider whether to protect the domestic industry from Chinese competition.
            Assess whether the domestic industry heavily relies on the Chinese market and consider the losses after imposing tariffs.
            Consider if China has taken substantive countermeasures or sanctions and their impact on the interests of related industries.
            Evaluate the above interests.
        5. Consider foreign trade and international relations with China:
            Assess the impact of China's countermeasures on foreign trade.
        6. Consider historical and cultural background:
            Assess whether historical and cultural factors will influence the country's decision.
        7. Consider political and public opinion:
            Assess the domestic political environment and public opinion's support for the policy.
            Consider whether to align with public opinion.
        8. Consider domestic economic pressures:
            Assess the policy's impact on the domestic economy.
            Consider whether to impose tariffs or oppose tariffs to alleviate economic pressures.
        9. Consider relations with the EU:
            Assess the policy's impact on relations with the EU. Consider the EU's unified position and whether to respect the European Commission's opinion to impose tariffs.
        10. **Voting Rules**: The additional tariff on Chinese electric vehicles will only be canceled if the vote is rejected. Otherwise, the additional tariff on Chinese electric vehicles will still be imposed.

    # Decision Constraints
        # Decision Constraints
        - Prioritize national interests and the common interests of the EU, taking into account China's feedback as appropriate. Consider the findings of the European Commission's investigation and whether it is necessary to align with the Commission's stance. If national interests are severely compromised, it is imperative to prioritize national interests.
        - The initiating country of the investigation is unlikely to easily change its position.
        - If the domestic automotive or related industries are severely impacted by Chinese electric vehicles, or if the domestic related industries are limited but the decision is made to uphold the European Commission's decision, or if relations with China are poor, or if other countries or the European Commission offer sufficient benefits, it may be considered to agree.
        - If the impact of tariffs on domestic industries is limited, or if China's countermeasures do not significantly affect core industries, it is advisable to align with the European Commission's opinion and agree to impose tariffs.
        - If the country has significant interests in China or if domestic industries are heavily reliant on China, it is advisable to consider opposing or abstaining. Specific decisions should be made based on the following principles.
        - If domestic industries are confirmed to be affected by China's countermeasures and have suffered substantial losses, it may be considered to oppose.
        - If China's countermeasures could potentially lead to losses but have not yet been implemented, and in order to maintain a unified stance within the EU, balance national interests with the European Commission's intentions, or to avoid affecting trade and diplomatic relations with China, it may be considered to abstain.
        - If the economic contribution of the domestic automotive industry is minimal and there is a desire to avoid damaging economic and diplomatic relations with China, abstaining from the vote could be considered.
        - If the national leader has reached an agreement with China, the vote should be cast in accordance with the agreed terms.
        - If the benefits provided by the European Commission or other countries can compensate for the losses, the above constraints may be overridden and the vote cast as per their request.

   # Output Example
    - **Agree to Impose Tariffs**: r"```plaintext Agree   Specific reasons``` Reasons should be concise, around 100 words. Ensure strict format with NO other texts.
    - **Oppose Imposing Tariffs**: r"```plaintext Oppose   Specific reasons``` Reasons should be concise, around 100 words. Ensure strict format with NO other texts.
    - **Abstain**: r"```plaintext Abstain   Specific reasons``` Reasons should be concise, around 100 words. Ensure strict format with NO other texts.
    """

    name: str = "MakeConclusion"
    profile: str = "Based on contextual information and China's feedback, make the final decision on whether to agree to impose an additional 25% tariff on Chinese electric vehicles in the EU vote and provide reasons."

    async def run(self, msg: Message, country: Dict[str, Any], simu_round_number: int):
        context_make_decision = msg.content
        country_name = country["country_name"]
        if simu_round_number > 2:
            # Summarize the agent's memory, if the number of rounds is small, it may not be necessary. Construct prompt for LLM
            prompt1 = (
                f"Summarize the content of the text information by the sender's name, merge and remove duplicate content, highlight important information, one line per different sender.\n"
                f"Text information as follows: {msg.content}\n "
                f"- **Output Example**:\n"
                f"Domestic Industry Reactions Affected by China's Countermeasures: Automotive industry exports may be restricted, affecting GDP growth. Automotive industry unions may organize protests, urging the government to negotiate with China.\n"
                f"Communication from Germany: Germany sends communication to Spain, content: Support the protection of the EU internal market, coordinate positions, and strive to reach a consensus on the electric vehicle tariff issue.\n"
                f"Communication from Italy: Italy sends communication to Spain, proposing to increase support for Spain's automotive industry in the EU budget in exchange for Spain's support for tariffs on Chinese electric vehicles.\n"
            )
            context_make_decision = await self._aask(prompt1)
            await asyncio.sleep(5)

        prompt = self.PROMPT_TEMPLATE.format(country_name=country_name,
                                             context=context_make_decision,
                                             final_voting_results=country["final_voting_results"],
                                             china_feedback_and_communication=country[
                                                 "china_feedback_and_communication"],
                                             european_relations=country["european_relations"],
                                             government_interests=country["government_interests"],
                                             vote_info_of_home_country=country["vote_info_of_home_country"],
                                             diplomatic_Relations=country["diplomatic_Relations"],
                                             historical_and_Cultural_Background=country[
                                                 "historical_and_Cultural_Background"],
                                             political_and_Public_Opinion=country["political_and_Public_Opinion"],
                                             domestic_Economic_Pressures=country["domestic_Economic_Pressures"]
                                             )

        # print(f"Input message content for MakePreDecision: {msg.content}, message from {msg.sent_from}, MakePreDecision task completed")
        rsp = await self._aask(prompt)
        await asyncio.sleep(10)
        answer = parse_answer(rsp)

        msg = Message(content=answer, role=self.profile, cause_by="MakeConclusion",
                      sent_from=country["country_name"], send_to=f"Secretary_{country_name}")
        env.publish_message(msg)

        print("...................MakeConclusion..prompt.....................")
        print(prompt)

        print(f"Message content: {answer}, {country_name}, message from {msg.sent_from}, MakeConclusion task completed")
        # Write the answer content to a file
        # Get the current system time
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Specify the file name and path, file is in the current directory
        file_name = "preliminary_decision.txt"
        file_text = "Country: " + country["country_name"] + " Country's voting intention: " + parse_answer(rsp)
        # Open the file in append mode
        with open(file_name, 'a', encoding='utf-8') as file:
            # Write the string and time, then add a newline
            file.write(f"{file_text}, time: {current_time}\n")
        # Write the prompt content to a file
        # Specify the file name and path, file is in the current directory
        file_name2 = "decision_prompt.txt"
        file_text2 = "##############################\n" + "Country: " + country[
            "country_name"] + " Country's voting intention: " + parse_answer(
            rsp) + "\n" + prompt + "\n" + "Country's voting intention: " + parse_answer(rsp) + "\n"
        # Open the file in append mode
        with open(file_name2, 'a', encoding='utf-8') as file:
            # Write the string and time, then add a newline
            file.write(f"{file_text2}, time: {current_time}\n")
        return Message(content=answer, role=self.profile, cause_by="MakeConclusion",
                       sent_from=country["country_name"], send_to=f"Secretary_{country['country_name']}")


class CounteringActions(Action):
    name: str = "CounteringActions"
    profile: str = "As a Chinese official, determine countermeasures based on the aggregated voting results of various countries. These measures may include imposing retaliatory tariffs on certain products exported from the EU to China."
    async def run(self, msg: Message, simu_round_number: int):
        context_make_decision = msg.content
        print(f"..................Round {simu_round_number}, China sends countermeasures.....................")
        count_msg_1 = "Temporarily not considering China's countermeasures or retaliation"
        count_msg_2 = "China does not agree with or accept the ruling and has filed a lawsuit under the WTO dispute settlement mechanism. China will continue to take all necessary measures to resolutely safeguard the legitimate rights and interests of Chinese enterprises. The China Chamber of Commerce for Import and Export of Machinery and Electronic Products submitted a minimum price commitment plan for electric vehicle exports to the European Commission."
        count_msg_3 = "Initiate an anti-dumping investigation on brandy originating from the EU. Implement export controls on rare earth products (including but not limited to tungsten, tellurium, bismuth, molybdenum, indium-related items) exported to the EU. European Commission President Ursula von der Leyen mentioned that 98% of the EU's rare earths, 93% of magnesium, and 97% of lithium come from China, and these materials play a crucial role in the modern industrial system."
        count_msg_4 = "Initiate an anti-dumping investigation on pork originating from the EU."
        count_msg_5 = "Initiate an anti-dumping investigation on dairy products originating from the EU, involving several cheese, milk, and cream products imported from the EU."
        count_msg_6 = "Spanish Prime Minister Pedro Sánchez paid an official visit to China from September 8 to 11, 2024. The visit aimed to further promote bilateral relations between China and Spain, deepen cooperation in economic, trade, cultural, and tourism fields. Sánchez also expressed the willingness to resolve trade disputes through dialogue, emphasizing that both sides should seek consensus based on the principle of mutual benefit and win-win."
        count_msg = countrys_EU["Germany"]["china_feedback_and_communication"]
        count_msg_test = "Initiate an anti-dumping investigation on brandy originating from the EU. Initiate an anti-dumping investigation on dairy products originating from the EU, involving several cheese, milk, and cream products imported from the EU. Initiate an anti-dumping investigation on pork originating from the EU."
        msg = Message(content="", role=self.profile, cause_by="CounteringActions",
                      sent_from="China")
        if simu_round_number == 1:
            count_msg = count_msg_1
            for country in countrys_EU.keys():
                countrys_EU[country]["china_feedback_and_communication"] = count_msg
                msg = Message(content=count_msg_1, role=self.profile, cause_by="CounteringActions",
                          sent_from="China",send_to=f"Secretary_{country}")
                env.publish_message(msg)
            print(f"CounteringActions first message published, content: {count_msg}. /n")


        # For testing purposes, to save time, include all content in the second round
        elif simu_round_number == 2:
            count_msg =  count_msg_test
            for country in countrys_EU.keys():
                countrys_EU[country]["china_feedback_and_communication"] = count_msg
                countrys_EU[country]["final_voting_results"] = "Proposal to impose additional tariffs on Chinese electric vehicles passed"
                msg = Message(content=count_msg, role=self.profile, cause_by="CounteringActions",
                          sent_from="China",send_to=f"Secretary_{country}")
                env.publish_message(msg)
            print(f"CounteringActions second message published, content: {count_msg}. /n")
            #Germany
            countrys_EU["Germany"]["domestic_Economic_Pressures"] = "German automakers have joint ventures with Chinese automakers in China, and German automakers are strongly lobbying to oppose tariffs. Automotive companies oppose increasing tariffs on Chinese electric vehicle imports. China is the largest single market for Mercedes-Benz, Volkswagen, and BMW, accounting for about one-third of their total sales. China's countermeasures will affect German car sales in China." + \
                                                 countrys_EU["Germany"]["domestic_Economic_Pressures"]
            countrys_EU["Germany"]["government_interests"] = countrys_EU["Germany"]["government_interests"] + "VDA opposes increasing tariffs on Chinese electric vehicle imports."
            msg_germany = Message(content="German automakers have joint ventures with Chinese automakers in China, and German automakers are strongly lobbying to oppose tariffs. Automotive companies oppose increasing tariffs on Chinese electric vehicle imports. VDA opposes increasing tariffs on Chinese electric vehicle imports. China is the largest single market for Mercedes-Benz, Volkswagen, and BMW, accounting for about one-third of their total sales. China's countermeasures will affect German car sales in China.", role=self.profile, cause_by="CounteringActions",
                                sent_from="Secretary_Germany", send_to="Germany")
            env.publish_message(msg_germany)
            #Spain
            msg_spain = Message(content=count_msg_6, role=self.profile, cause_by="CounteringActions",
                          sent_from="China", send_to="Spain")
            countrys_EU["Spain"]["china_feedback_and_communication"] = count_msg_6
            print(f"CounteringActions sixth message published, content: {count_msg_6}. /n")
            env.publish_message(msg_spain)
            #European Commission 2 Ireland
            countrys_EU["Ireland"][
                "government_interests"] = countrys_EU["Ireland"][
                                              "government_interests"] + "At present the Chinese complaint relates to a subsector of dairy products, such as cheeses. And most of our cheese exports are directed to the UK and EU markets."
            countrys_EU["Ireland"][
                "european_relations"] = "The European Commission promises: The EU market will provide support for Ireland's dairy exports to compensate for Ireland's losses, hoping Ireland will support the European Commission's investigation results, maintain the EU's unified position, and vote in favor." + \
                                        countrys_EU["Ireland"]["european_relations"]
            eu_commission_msg = Message(
                content="The European Commission promises: The EU market will provide support for Ireland's dairy exports to compensate for Ireland's losses, hoping Ireland will support the European Commission's investigation results, maintain the EU's unified position, and vote in favor.",
                cause_by="EuCommissionReact",
                send_to="Ireland")
            env.publish_message(eu_commission_msg)
            print(f"EuCommissionReact first message published, target: Ireland, content: {eu_commission_msg.content}. /n")


        # If using testing, only use the second round data for testing, the official second round can be commented out
        # elif simu_round_number == 2:
        #     count_msg =  count_msg_2
        #     for country in countrys_EU.keys():
        #         countrys_EU[country]["china_feedback_and_communication"] = count_msg
        #         msg = Message(content=count_msg, role=self.profile, cause_by="CounteringActions",
        #                   sent_from="China",send_to=f"Secretary_{country}")
        #         env.publish_message(msg)
        #     countrys_EU["Germany"][
        #         "domestic_Economic_Pressures"] = "German automakers have joint ventures with Chinese automakers in China, and German automakers are strongly lobbying to oppose tariffs. Automotive companies oppose increasing tariffs on Chinese electric vehicle imports." + \
        #                                          countrys_EU["Germany"]["domestic_Economic_Pressures"]
        #     countrys_EU["Germany"][
        #         "government_interests"] = countrys_EU["Germany"]["government_interests"] + "VDA opposes increasing tariffs on Chinese electric vehicle imports."
        #
        #     print(f"CounteringActions second message published, content: {count_msg}. /n")

        elif simu_round_number == 3:
            count_msg = count_msg+count_msg_3
            for country in countrys_EU.keys():
                countrys_EU[country]["china_feedback_and_communication"] = count_msg
                msg = Message(content=count_msg, role=self.profile, cause_by="CounteringActions",
                              sent_from="China", send_to=f"Secretary_{country}")
                env.publish_message(msg)
            print(f"CounteringActions third message published, content: {count_msg}. /n")
        elif simu_round_number == 4:
            count_msg = count_msg + count_msg_4
            for country in countrys_EU.keys():
                countrys_EU[country]["china_feedback_and_communication"] = count_msg
                msg = Message(content=count_msg, role=self.profile, cause_by="CounteringActions",
                              sent_from="China", send_to=f"Secretary_{country}")
                env.publish_message(msg)
            print(f"CounteringActions fourth message published, content: {count_msg}. /n")
        elif simu_round_number == 5:
            count_msg = count_msg + count_msg_5
            for country in countrys_EU.keys():
                countrys_EU[country]["china_feedback_and_communication"] = count_msg
                msg = Message(content=count_msg, role=self.profile, cause_by="CounteringActions",
                              sent_from="China", send_to=f"Secretary_{country}")
                env.publish_message(msg)
            countrys_EU["Ireland"][
                "government_interests"] = countrys_EU["Ireland"][
                                              "government_interests"] + "At present the Chinese complaint relates to a subsector of dairy products, such as cheeses. And most of our cheese exports are directed to the UK and EU markets."
            countrys_EU["Ireland"]["european_relations"] = "The European Commission promises: The EU market will provide support for Ireland's dairy exports to compensate for Ireland's losses, hoping Ireland will support the European Commission's investigation results, maintain the EU's unified position, and vote in favor." + countrys_EU["Ireland"]["european_relations"]
            eu_commission_msg = Message(
                content="The European Commission promises: The EU market will provide support for Ireland's dairy exports to compensate for Ireland's losses, hoping Ireland will support the European Commission's investigation results, maintain the EU's unified position, and vote in favor.",
                cause_by="EuCommissionReact",
                send_to="Ireland")
            env.publish_message(eu_commission_msg)
            print(f"CounteringActions fifth message published, content: {count_msg}. /n")
        elif simu_round_number == 6:
            count_msg = count_msg_6
            #China and Spanish Prime Minister meet, achieve phased results
            msg = Message(content=count_msg, role=self.profile, cause_by="CounteringActions",
                          sent_from="China", send_to="Spain")
            countrys_EU["Spain"]["china_feedback_and_communication"] =count_msg
            print(f"CounteringActions sixth message published, content: {count_msg}. /n")
            env.publish_message(msg)

        return msg

class SecretaryAction(Action):
    name: str = "SecretaryAction"
    profile: str = "Secretary agent's action"

    def __init__(self, country_data: Dict[str, Any], **kwargs):
        super().__init__(**kwargs)  # Pass any additional kwargs to the parent class
        self.country_data = country_data

    async def run(self, msg: Message, country_data: Dict[str, Any]):
        global vote_round_number
        n_round = vote_round_number
        print(f"Current n_round is {n_round}, action read as {SecretaryAction}")
        home_country = country_data["country_name"]
        if msg.cause_by in ["MakePreDecision", "MakeConclusion"]:
            if n_round < 2:
                # Directly send to VoteRecorder
                vote_recorder_msg = Message(content=msg.content, role=self.profile, cause_by="SecretaryAction",
                                            sent_from=msg.sent_from, send_to="VoteRecorder")
                env.publish_message(vote_recorder_msg)
                print(f"SecretaryAction at n_round={n_round}, directly sends message to VoteRecorder, MakeConclusion, message content: {msg.content}.")
                # If opposing or abstaining, send the European Commission's feedback to the country agent
                # if "Oppose" in msg.content or "Abstain" in msg.content :
                #     eu_commission_react_text = await self.eu_commission_react(msg, country_data)
                #     eu_commission_msg = Message(content=eu_commission_react_text, role=self.profile,
                #                                 cause_by="EuCommissionReact",
                #                                 sent_from=f"Secretary_{msg.sent_from}", send_to=msg.sent_from)
                #     env.publish_message(eu_commission_msg)
                #     print(
                #         f"SecretaryAction forwards EuCommissionReact message, message from {eu_commission_msg.sent_from}, sent to {eu_commission_msg.send_to}, message content: {eu_commission_msg.content}.")
                return vote_recorder_msg
            else:
                answer = await self.is_decision_acceptable(msg.content)
                if "Oppose" in answer:
                    # Send feedback to the country agent, including reasons
                    feedback_reason = answer.split("Reason")[1] if "Reason" in answer else "No specific reason"
                    feedback_msg = Message(content=f"Please reconsider. Reason: {feedback_reason}", role=self.profile,
                                           cause_by="SecretaryAction", sent_from=self.name, send_to=msg.sent_from)
                    env.publish_message(feedback_msg)
                    print(f"SecretaryAction finds it unreasonable, message from {msg.sent_from}, MakeConclusion, message content: {msg.content}.")
                    return feedback_msg

                else:
                    # Send to VoteRecorder
                    vote_recorder_msg = Message(content=msg.content, role=self.profile, cause_by="SecretaryAction",
                                                sent_from=msg.sent_from, send_to="VoteRecorder")
                    env.publish_message(vote_recorder_msg)
                    print(f"SecretaryAction finds it reasonable, message from {msg.sent_from}, MakeConclusion, message content: {msg.content}.")
                    # Send the European Commission's feedback to the country agent
                    eu_commission_react_text =await self.eu_commission_react(msg, country_data)
                    eu_commission_msg =Message(content= eu_commission_react_text, role=self.profile, cause_by="EuCommissionReact",
                                                sent_from=f"Secretary_{msg.sent_from}", send_to=msg.sent_from)
                    env.publish_message(eu_commission_msg)
                    print(f"SecretaryAction forwards EuCommissionReact message, message from {eu_commission_msg.sent_from}, sent to {eu_commission_msg.send_to}, message content: {eu_commission_msg.content}.")
                    return vote_recorder_msg
        elif msg.cause_by == "DecideCommunication":
            answer = await self.is_information_important(msg, country_data)
            if "No" in answer:
                print(
                    f"Country {home_country}'s SecretaryAction considers the message from {msg.sent_from} unimportant, message content: {msg.content}.")
            else:
                # Forward to the country agent
                forward_msg = Message(content=msg.content, role=self.profile, cause_by="DecideCommunication",
                                      sent_from=msg.sent_from, send_to=home_country)
                env.publish_message(forward_msg)
                print(f"SecretaryAction forwards message to {forward_msg.send_to}, DecideCommunication, message content: {msg.content}.")

        elif msg.cause_by == "CounteringActions" :
            industry_react_text =await self.industry_react(msg,country_data)
            forward_msg = Message(content=industry_react_text, role=self.profile, cause_by="CounteringActions",
                                  sent_from=msg.sent_from, send_to=home_country)
            env.publish_message(forward_msg)
            print(f"SecretaryAction forwards domestic industry reactions to {forward_msg.send_to}, DecideCommunication, message content: {msg.content}.")
        return msg
    async def is_decision_acceptable(self, decision):
        # Construct prompt
        prompt = (
            f"Based on the following country data and background information and the European Commission's investigation results, if there is obvious unreasonableness, oppose the decision, otherwise agree:\n"
            f"Country data: {self.country_data}\n"
            f"European Commission investigation results: Indicate that recent large-scale imports of low-priced and subsidized Chinese electric vehicles into the EU pose an economic threat to the EU's electric vehicle industry."
            f"Decision: {decision}\n"
            f"- **Output Example**:"
            f"  Agree or Oppose Reason: Specific reason \n"
            f"  Output in the same line, no line breaks, content concise, no more than 50 words with NO other texts\n"
        )
        # Call LLM for answer
        try:
            # Cancel secretary's judgment on whether to agree
            # answer = await self._aask(prompt)
            # print(f"Secretary judges whether the country agrees, specific content: {answer}")
            # await asyncio.sleep(10)
            answer = "Agree"
            return answer
        except Exception as e:
            logger.error(f"Error judging decision acceptability: {e}")
            return "No Reason: System error"

    async def is_information_important(self, msg:Message, country_data):
        # Construct prompt for LLM
        prompt3 = f"Based on the following country data, judge whether the following information is true and important:\nHome country data: {country_data}\nSender country: {msg.sent_from}\nMessage content: {msg.content}\nBasic principles: Information from powerful countries can influence weaker countries, but not vice versa. If the sender country's GDP is less than one-third of the home country's, it can be ignored. If the information is unrealistic, it can be ignored.\n- **Output Example**: 'Yes' or 'No'."
        # Call LLM asynchronously

        answer = await self._aask(prompt3)
        await asyncio.sleep(10)
        print(f"SecretaryAction's judgment on whether the information is important: {answer}")
        print(f"SecretaryAction reads country information as follows: {msg.content}, sender country: {msg.sent_from}, accepted: {answer}")

        return answer
    async def industry_react(self, msg:Message, country_data):
        # Construct prompt for LLM
        prompt = (
            f"Based on the following country data and China's countermeasures, determine which domestic industries will be affected and what actions they will take towards the government:\n"
            f"Country data: {country_data}\n"
            f"China's countermeasures content: {msg.content}\n"
            f"Basic principles: First determine if the country has industries affected by the countermeasures, then calculate the losses caused by the countermeasures. Only consider industries explicitly affected by the countermeasures. Only when the losses are particularly severe may industry personnel or unions organize protests or pressure the government. If the affected industries' losses are not significant, no drastic reactions will occur. Only list industries that need to react.\n"
            f"Example: China initiates an anti-dumping investigation on EU brandy, and France, as the main exporter of EU brandy (accounting for 99% of EU brandy exports to China), with French brandy exports to China amounting to approximately 1.7 billion euros, is significantly affected. The French brandy industry fears that anti-dumping measures may lead to price increases in the Chinese market. French brandy industry practitioners, including grape growers, wineries, and traders, are pressuring the Macron government, and French farmers and winemakers have even taken to the streets to protest.\n"
            f"Example: China initiates an anti-dumping investigation on EU dairy products, but Ireland's dairy products are highly diversified in product types and export destinations. Currently, China's complaint targets certain subcategories of dairy products, such as cheese. And most of Ireland's cheese exports are directed to the UK and EU markets. Therefore, the overall impact on Ireland's dairy industry is limited, and the domestic industry has no specific reactions.\n"
            f"- **Output Example**:\n"
            f"  Industry Name  Impact  Actions taken by relevant personnel towards the government \n"
            f"  Content concise, no more than 100 words with NO other texts\n"
        )
        # Call LLM asynchronously

        answer = await self._aask(prompt)
        print(f"SecretaryAction reads country information as follows: {msg.content}, sender country: {msg.sent_from}, impact and measures: {answer}")
        await asyncio.sleep(10)
        return answer
    async def eu_commission_react(self, msg:Message, country_data):
        # Construct prompt for LLM
        prompt = (
            f"Based on the decision-making country's data and the decision made, judge whether it aligns with the European Commission's goals and send a message to them:\n"
            f"Country data: {country_data}\n"
            f"Decision made on voting for tariffs on Chinese electric vehicles: {msg.content}\n"
            f"European Commission investigation results: The European Commission released a report stating: Sufficient evidence has been collected to indicate that recent large-scale imports of low-priced and subsidized Chinese electric vehicles into the EU pose an economic threat to the EU's electric vehicle industry. The European Commission believes: The EU urgently needs to prevent the EU's electric vehicle industry from suffering a fate similar to that of China's solar panel industry. While consumers may benefit from cheaper Chinese cars in the short term, allowing unfair practices may ultimately lead to reduced competition and higher prices in the long term.\n"
            f"- **Output Example**:\n"
            f"  European Commission  Hopes for a specific vote  As the European Commission's communication message to the country  \n"
            f"  Content concise, no more than 100 words with NO other texts\n"
        )
        # Call LLM asynchronously

        answer = await self._aask(prompt)
        print(f"SecretaryAction reads the country's decision as follows: {msg.content}, sender country: {msg.sent_from}, European Commission's communication message: {answer}")
        await asyncio.sleep(10)
        return answer

class ChairMan(Role):
    name: str = "EuChairMan"
    profile: str = "EU_ChairMan"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.simu_round_number = 1  # Add an attribute to store the round number
        self._watch({UserRequirement})  # UserRequirement is the default cause_by value for Message
        self.set_actions([StartToVote])

    async def _act(self) -> Message:
        logger.info(f"{self._setting}: to do {self.rc.todo}({self.rc.todo.name})")
        todo = self.rc.todo  # todo will be StartToVote()
        msg = self.get_memories(k=0)[0]  # Find the most recent messages
        task_value = await todo.run(msg)

        print("EuChairMan task completed")
        return task_value


class VoteRecorder(Role):
    name: str = "VoteRecorder"
    profile: str = "Record the vote result"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.simu_round_number = 1  # Add an attribute to store the round number
        self._watch({SecretaryAction})  # Observe VoteRecordAction
        self.set_actions([VoteRecordAction])

    async def _act(self) -> Message:
        logger.info(f"{self._setting}: to do {self.rc.todo}({self.rc.todo.name})")
        todo = self.rc.todo  # todo will be VoteRecordAction()
        news = self.rc.news

        task_result = ""
        for msg in news:
            task_result = await todo.run(msg, simu_round_number=self.simu_round_number)
            print(f"VoteRecorder received a message from {msg.sent_from}, content: {msg.content}, simu_round_number value: {self.simu_round_number}.")

        print("VoteRecorder task completed")
        return task_result


class SecretaryRole(Role):
    profile: str = "As the secretary of the national agent, judge whether its decisions align with national interests, and determine the importance of information received from other countries, forwarding important ones to the national agent for processing."
    goal: str = "Ensure the rationality of the national agent's decisions and filter the importance of information received from other countries."

    def __init__(self, country_name, country_data, **kwargs):
        super().__init__(**kwargs)
        self.simu_round_number = 1  # Add an attribute to store the round number
        self.country_name = country_name
        self.country_data = country_data
        self.set_actions([SecretaryAction(country_data=self.country_data, config=llm_secretary)])  # Pass country_data to SecretaryAction
        self._set_react_mode(react_mode=RoleReactMode.BY_ORDER.value)
        self._watch([DecideCommunication, MakeConclusion])

    async def _act(self) -> Message:
        logger.info(f"{self._setting}: to do {self.rc.todo}({self.rc.todo.name})")

        todo = self.rc.todo
        news = self.rc.news
        result_msg = message("SecretaryRole task completed")

        for msg in news:
            print(f"SecretaryRole of country {self.country_name} received a message: {msg.content}, from {msg.sent_from}.")
            result = await todo.run(msg, self.country_data)

        return result_msg


class EuCountry(Role):
    name: str = "Germany"
    profile: str = "Based on national information and communication with other countries, decide whether to vote in favor, against, or abstain on the imposition of tariffs on Chinese electric vehicles, while communicating with other countries and proposing related agreements or positions."
    country_memory: str = ""
    # goal: str = "To make a decision on the tariff imposition that maximizes the country's economic and political interests while considering the collective EU stance."
    # constraints: str = "The decision must align with EU regulations, consider the country's economic health, public opinion, and the potential impact on diplomatic relations with China."
    # desc: str = """
    #         This agent has the following capabilities:
    #         - DecideCommunication: Select countries to communicate with and send them communication messages
    #         - MakeConclusion: Based on contextual information and feedback from China, make a preliminary decision on whether to support the EU vote to impose an additional 25% tariff on Chinese electric vehicles, and send it to the national secretary for confirmation
    #         """

    def __init__(self, country_data: Dict[str, Any], **kwargs):
        super().__init__(**kwargs)
        self.country_data = country_data  # Initialize country_data
        self.simu_round_number = 1  # Add an attribute to store the round number
        self.set_actions([MakeConclusion, DecideCommunication(config=llm_secretary)])
        self._set_react_mode(react_mode=RoleReactMode.BY_ORDER.value)
        self._watch([StartToVote, SecretaryAction])

    async def _act(self) -> Message:
        logger.info(f"{self._setting}: to do {self.rc.todo}({self.rc.todo.name})")
        country_name = self.name
        todo = self.rc.todo
        news = self.rc.news
        memories = self.get_memories()  # Get all memories
        # There is still an issue here
        # memories = [msg for msg in memories if msg.send_to == self.name]
        # Initialize context

        # Attempt to update memories with news

        context = ""
        # Merge contextual information from memory
        for memory in news:
            print(f"National agent: {self.name}, received memory: {memory.content}, from {memory.sent_from}, action: {memory.cause_by}")
            if memory.cause_by == "SecretaryAction":
                # Secretary's feedback
                context += f"Secretary Feedback, sent from: {memory.sent_from}, content: {memory.content}\n"
            elif memory.cause_by == "DecideCommunication":
                # Communication from other countries
                context += f"Communication from {memory.sent_from}: {memory.content}\n"
            elif memory.cause_by == "CounteringActions":
                # Domestic industry reactions affected by China's countermeasures
                context += f"Domestic Industry Reactions Affected by China's Countermeasures: {memory.content}\n"
            elif memory.cause_by == "EuCommissionReact":
                # Communication from the European Commission
                context += f"Communication from European Commission: {memory.content}\n"
            elif memory.cause_by == "VoteRecordAction":
                # Previous round's voting result
                context += f"Previous Voting Result: {memory.content}\n"

        self.country_memory = self.country_memory + context
        result = await todo.run(Message(content=self.country_memory, role=self.profile, cause_by="Eu_countries"),
                                self.country_data, self.simu_round_number)
        return result
# Define the Role class
class China(Role):
    name: str = "China"
    profile: str = "ChineseDelegate"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.simu_round_number = 1  # Add an attribute to store the round number
        # Import the predefined Action class
        self.set_actions([CounteringActions])
        self._set_react_mode(react_mode=RoleReactMode.BY_ORDER.value)
        self._watch([StartToVote])

    async def _act(self) -> Message:
        logger.info(f"{self._setting}: to do {self.rc.todo}({self.rc.todo.name})")
        todo = self.rc.todo
        print(f"China starts, action: {todo.name}")
        msg = self.get_memories(k=0)[0]  # Find the most recent messages
        task_value = await todo.run(msg, self.simu_round_number)

        print("China task completed")
        return task_value


async def main(
        idea: str = "Run simulation",
        investment: float = 10.0,
        n_round: int = 3,
):
    logger.info(idea)

    # Initialize several record files
    with open('preliminary_decision.txt', 'w', encoding='utf-8') as file:
        pass
    with open('communication_information.txt', 'w', encoding='utf-8') as file:
        pass
    with open('decision_prompt.txt', 'w', encoding='utf-8') as file:
        pass

    # Initialize an Excel file
    wb = openpyxl.Workbook()
    wb.save('vote_results.xlsx')

    # Instantiate a team
    eu_vote2_cn_ev = Vote(name="EU_Vote_2_CN_EV_1", disc="Simulate EU vote on imposing tariffs on Chinese electric vehicles")
    eu_vote2_cn_ev.hello()

    # Instantiate countries as Role classes
    # Instantiate countries with country_data
    germany = EuCountry(name="Germany", profile="Represents Germany voting on additional tariffs on Chinese electric vehicles",
                        country_data=countrys_EU["Germany"])
    france = EuCountry(name="France", profile="Represents France voting on additional tariffs on Chinese electric vehicles", country_data=countrys_EU["France"])
    italy = EuCountry(name="Italy", profile="Represents Italy voting on additional tariffs on Chinese electric vehicles", country_data=countrys_EU["Italy"])
    spain = EuCountry(name="Spain", profile="Represents Spain voting on additional tariffs on Chinese electric vehicles", country_data=countrys_EU["Spain"])
    netherland = EuCountry(name="Netherland", profile="Represents the Netherlands voting on additional tariffs on Chinese electric vehicles",
                           country_data=countrys_EU["Netherland"])
    denmark = EuCountry(name="Denmark", profile="Represents Denmark voting on additional tariffs on Chinese electric vehicles",
                        country_data=countrys_EU["Denmark"])
    ireland = EuCountry(name="Ireland", profile="Represents Ireland voting on additional tariffs on Chinese electric vehicles",
                        country_data=countrys_EU["Ireland"])

    china = China(name="China", profile="China's response to EU tariff actions")

    # Instantiate a chairman as a Role class
    eu_chairman = ChairMan()

    vote_recorder = VoteRecorder()
    # Add roles to the environment
    env.add_roles([eu_chairman, vote_recorder, china, germany, france, italy, spain, netherland, denmark, ireland])
    # Add roles to the team class
    eu_vote2_cn_ev.hire([eu_chairman, vote_recorder, china, germany, france, italy, spain, netherland, denmark, ireland])

    # Add secretary agents during environment initialization
    secretaries = {}
    for country in countrys_EU.keys():
        secretary = SecretaryRole(country_name=country, country_data=countrys_EU[country], name=f"Secretary_{country}", profile=f"{country} Secretary")
        secretaries[country] = secretary
        env.add_roles([secretary])
        eu_vote2_cn_ev.hire([secretary])

    # Simulate several countries in a loop, simulating for a certain number of rounds

    print(f"################## Simulation starts, running now #######################")
    eu_vote2_cn_ev.invest(investment=investment)

    simu_round_number: int
    for simu_round_number in range(2):
        print(f"################## Round {simu_round_number + 1} simulation #######################")
        # Add an identifier to the preliminary decision file
        # Get the current system time
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Specify the file name and path, the file is in the current directory
        file_name = "preliminary_decision.txt"
        file_name2 = "communication_information.txt.txt"
        file_name3 = "decision_prompt.txt"
        # Open the file in append mode
        with open(file_name, 'a', encoding='utf-8') as file:
            # Write the string and time, then add a newline
            file.write(f"################## Round {simu_round_number + 1} simulation #######################, time: {current_time}\n")
        with open(file_name2, 'a', encoding='utf-8') as file:
            # Write the string and time, then add a newline
            file.write(f"################## Round {simu_round_number + 1} simulation #######################, time: {current_time}\n")
        with open(file_name3, 'a', encoding='utf-8') as file:
            # Write the string and time, then add a newline
            file.write(f"################## Round {simu_round_number + 1} simulation #######################, time: {current_time}\n")

        for member in [eu_chairman, vote_recorder, china, germany, france, italy, spain, netherland, denmark, ireland]:
            member.simu_round_number = simu_round_number + 1
        print(f"Current round_number value in China: {china.simu_round_number}")
        eu_vote2_cn_ev.run_project(eu_vote2_cn_ev.disc)
        # No communication in the first round, set n_round=2, start running according to the set value from the second round
        if simu_round_number == 0:
            await eu_vote2_cn_ev.run(n_round=1)
            await asyncio.sleep(10)
        else:
            await eu_vote2_cn_ev.run(n_round=n_round)
            await asyncio.sleep(10)
        # Summarize voting results
        vote_recorder_msg = Message(content="Summarize voting results", role="VoteRecorder", cause_by="VoteRecorder", send_to="VoteRecorder")
        env.publish_message(vote_recorder_msg)
        await vote_recorder.run()
        await asyncio.sleep(5)
        determine_vote_pass(countrys_EU)
        


if __name__ == "__main__":
    fire.Fire(main)

