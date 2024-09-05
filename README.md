# Purpose of the bot

It was created as a proof of concept and also a gift to one of my friends who has a Discord server with more than 1000 users. The first request was to create a bot that would notify the server about users' birthdays and allow users to add their birthdays to the bot's database.
The bot currently has way more features as the project naturally grew and as server users asked for more little things to be added.

***Although it is a public repository, the bot requires additional setup to run on any other server. Most of the command descriptions are in russian and are currently not translated. Also, the chatGPT instructions are hardcoded for the time being. 
It will likely be modified to have a config file or a built-in server setup procedure for the bot to be more easily deployable on other servers when I have the time.***

## Supported commands

## OpenAI integration
The bot is waiting to be mentioned in the channel, specified in the .env file and requests a chatGPT response from OpenAI API. It also supports a dialogue with a user ID check to make sure he gets follow-up questions from the same user who originally asked the question. Currently, the dialogue length is 5 messages per user just a cost-saving measure and also to fit into the token size of GPT 3.5-turbo.

![image](https://github.com/l1ghtny/regular_bot/assets/47033558/3edbe86c-4226-4f8a-9943-c641e2622cd9)


## Other Modules

### Birthday check module
Every hour the bot checks all the recorded birthday dates with consideration of specified timezones. If any user has a birthday starting from this hour, they get a shoutout in the specified channel and get a specified birthday role for 24 hours. After the birthday check bot checks if any user's birthday role has been added more than 24 hours ago and removes the role in case it was.
Also, there is a check for users who deleted their accounts or left the server. If an account is deleted, the user's info gets deleted from the database to avoid getting errors when asking user's name from the discord API. If the user has left the server, he is flagged as absent and not included in the birthday date check until he comes back. If he is absent for more than a year, his info is deleted completely. 

### Voice channels creation

### Twitter links replacement

## In progress

### Admin features
