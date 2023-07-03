# Pollover is a Discord bot that allows users to create polls in discord servers, as well as fetch random trivia questions from an API for users to answer

import discord
import os
import sqlite3
import requests
import random
import html
from discord import option
from http_server import start_server

# Instantiating a bot object
bot = discord.Bot()

# Retrieving the bot token from environmental variable
bot_token = os.environ['TOKEN']

# Making the connection with the sqlite3 polls database
db = sqlite3.connect("polls")

# Clear DB:
# db.execute("DROP TABLE poll")
# db.execute("DROP TABLE poll_options")
# db.execute("DROP TABLE votes")

# Creating a table which contains the name and author and description of a poll
db.execute(
  "CREATE TABLE IF NOT EXISTS poll (name TEXT PRIMARY KEY NOT NULL, author TEXT NOT NULL, description TEXT NOT NULL);"
)

# Creating a table which saves all options for a poll.
db.execute(
  "CREATE TABLE IF NOT EXISTS poll_options (id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, name TEXT NOT NULL, poll_name TEXT NOT NULL, FOREIGN KEY(poll_name) REFERENCES poll(name) ON DELETE CASCADE);"
)

# Creating a table which saves all votes for a poll.
db.execute(
  "CREATE TABLE IF NOT EXISTS votes (id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, voter TEXT NOT NULL, poll_name TEXT NOT NULL, option TEXT NOT NULL, FOREIGN KEY(option) REFERENCES poll_options(name) ON DELETE CASCADE, FOREIGN KEY(poll_name) REFERENCES poll(name) ON DELETE CASCADE);"
)


# Helper function for returning option object list for the SelectVote class
def options_maker(poll_name):
  option_query = db.execute(
    "SELECT name FROM poll_options WHERE poll_name = ?", (poll_name, ))
  option_query = option_query.fetchall()
  options_vote_view = []

  for option_var in option_query:
    option_name = option_var[0]
    option_object = discord.SelectOption(label=option_name, value=option_name)
    options_vote_view.append(option_object)

  return options_vote_view


# Helper function for returning trivia answers object list for the SelectTrivia class
def trivia_options(answers):
  answer_trivia_view = []

  for answer in answers:
    answer_object = discord.SelectOption(label=answer, value=answer)
    answer_trivia_view.append(answer_object)

  return answer_trivia_view


# Helper function for returning progress bar string
def get_progress(num):
  num = int(num)
  progress_bar = ""

  for bar in range(num):
    progress_bar += "I"

  return progress_bar


# Helper function for getting stats of the poll
def get_stats(poll_name):
  options = db.execute("SELECT name FROM poll_options WHERE poll_name = ?",
                       (poll_name, ))
  options = options.fetchall()
  options_list = []
  votes_list = []

  stats_string = "The stats of the poll:\n"
  votes_sum = 0

  for option_var in options:
    option_name = option_var[0]
    options_list.append(option_name)
    count = db.execute(
      "SELECT COUNT(id) FROM votes WHERE poll_name = ? AND option = ?",
      (poll_name, option_name))
    count = count.fetchall()
    count = int(count[0][0])
    votes_sum += count
    votes_list.append(count)

  for i in range(len(options_list)):

    percentage = (votes_list[i] / votes_sum) * 100
    bar = get_progress(percentage)
    stats_string += f"{options_list[i]}:\n{bar} {percentage}% ({votes_list[i]} votes)\n"

  return stats_string


# Helper function for removing hash from discord username (this function is not used in this code but i kept it anyway)
def remove_hash(author):
  index_rmv = len(author) - 5
  new_author = ""
  for i in range(len(author)):
    if i == index_rmv:
      pass
    else:
      new_author = new_author + author[i]

  return new_author


# Class for representing vote options in a dropdown for the vote view. Subclass of the Discord Select class.
class SelectVote(discord.ui.Select):

  def __init__(self, view, poll_name):
    self._view = view
    self.poll_name = poll_name
    options = options_maker(self.poll_name)
    super().__init__(placeholder="Vote Options",
                     max_values=1,
                     min_values=1,
                     options=options)

  async def callback(self, interaction: discord.Interaction):
    option_selected = self.values[0]
    user_var = str(interaction.user)
    poll_check = db.execute("SELECT name FROM poll WHERE name = ?",
                            (self.poll_name, ))
    poll_check = poll_check.fetchall()
    if len(poll_check) == 0:
      await interaction.response.send_message("This poll has been closed.",
                                              ephemeral=True)
      return

    option_check = db.execute(
      "SELECT option FROM votes WHERE voter = ? AND poll_name = ?",
      (user_var, self.poll_name))
    option_check = option_check.fetchall()
    if len(option_check) != 0:
      await interaction.response.send_message(
        f"You already voted for {option_check[0][0]}!", ephemeral=True)
      return

    db.execute("INSERT INTO votes (voter, poll_name, option) VALUES (?, ?, ?)",
               (user_var, self.poll_name, option_selected))
    db.commit()
    await interaction.response.send_message(
      f"You voted for {self.values[0]}\n{get_stats(self.poll_name)}",
      ephemeral=True)


# Class for representing the view that is sent after a successfull /poll command. Subclass of the Discord View class
class VoteView(discord.ui.View):

  def __init__(self, poll_name, *, timeout=None):
    self.poll_name = poll_name
    super().__init__(timeout=timeout)
    self.add_item(SelectVote(self, self.poll_name))


# Class for representing trivia answers in a dropdown for the trivia view. Subclass of the Discord Select class.
class SelectTrivia(discord.ui.Select):

  def __init__(self, view, correct_answer, answers):
    self._view = view
    self.correct_answer = correct_answer
    self.answers = answers
    options = trivia_options(answers)
    super().__init__(placeholder="Vote Options",
                     max_values=1,
                     min_values=1,
                     options=options)

  async def callback(self, interaction: discord.Interaction):
    option_selected = self.values[0]

    if str(option_selected) == self.correct_answer:
      await interaction.response.send_message("You are correct!",
                                              ephemeral=True)

      return

    await interaction.response.send_message("You are wrong!", ephemeral=True)


# Class for representing the view that is sent after a /trivia command. Subclass of the Discord View class
class TriviaView(discord.ui.View):

  def __init__(self, correct_answer, answers, *, timeout=None):
    self.correct_answer = correct_answer
    self.answers = answers
    super().__init__(timeout=timeout)
    self.add_item(SelectTrivia(self, self.correct_answer, self.answers))


@bot.event
async def on_ready():
  print('Ready!')


# /poll command for creating polls. Takes name, options and description (optional) as arguments then sends the poll with a dropdown menu for selecting the vote.
@bot.command(name='poll', description="Creates a poll.")
@option("name", description="Poll name (used as a unique identifier)")
@option("options",
        description="Options (options separated by tilde character (~))")
@option("description", description="Poll Description", default="")
async def poll(ctx, name: str, options: str, description: str):

  if bot.user == ctx.author:
    return

  check_taken = db.execute("SELECT name FROM poll WHERE name = ?", (name, ))
  check_taken = check_taken.fetchall()
  if len(check_taken) != 0:
    await ctx.respond("This name is already taken.", ephemeral=True)
    return

  options = options.split("~")
  for option_var in options:
    option_var = option_var.strip()
    if len(option_var) > 30:
      await ctx.respond(
        "Please provide options of 30 characters or less each.",
        ephemeral=True)
      return

  if len(options) <= 1:
    await ctx.respond(
      "Must provide more than one option (separated by spaces and use quotation marks if more than one word).",
      ephemeral=True)
    return

  if len(name) > 30 or len(description) > 300:
    await ctx.respond(
      "Please provide a name of 30 characters or less and a description of 300 characters or less",
      ephemeral=True)
    return

  author = str(ctx.author)

  db.execute("INSERT INTO poll (name, author, description) VALUES (?, ?, ?)",
             (name, author, description))

  for option_var in options:
    db.execute("INSERT INTO poll_options (name, poll_name) VALUES (?, ?)",
               (option_var, name))

  db.commit()

  await ctx.respond(description, view=VoteView(name))


# /closepoll command for ending polls. Takes poll name as argument. Must be poll creator to end the poll.
@bot.command(name='closepoll', description="Closes a poll.")
@option("name", description="Poll name")
async def close_poll(ctx, name: str):

  author = str(ctx.author)

  all_polls = db.execute("SELECT * FROM poll WHERE name = ? AND author = ?",
                         (name, author))
  all_polls = all_polls.fetchall()
  if len(all_polls) == 0:
    await ctx.respond(
      "Request Failed. Please make sure that the poll name is correct and that you're the author of the poll.",
      ephemeral=True)
    return

  stats_string = get_stats(name)
  await ctx.respond(f"Poll of name {name} is over.\n{stats_string}")

  db.execute("DELETE FROM poll WHERE name = ?", (name, ))

  db.commit()


# /trivia command for extracting a random trivia question from Open Trivia DB API (https://opentdb.com/). Takes no additional arguments, then sends the question with a dropdown menu for the answers.
@bot.command(name='trivia', description="Gets a trivia question")
async def trivia(ctx):

  response = requests.get("https://opentdb.com/api.php?amount=1").json()

  question = response["results"][0]["question"]

  question = html.unescape(question)

  correct_answer = response["results"][0]["correct_answer"]

  incorrect_answers = response["results"][0]["incorrect_answers"]

  answers = []

  answers.append(correct_answer)

  for answer in incorrect_answers:
    answers.append(html.unescape(answer))

  random.shuffle(answers)

  await ctx.respond(question, view=TriviaView(correct_answer, answers))


start_server()
bot.run(bot_token)
