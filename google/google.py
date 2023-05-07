import asyncio
import functools
import json
import re
import aiohttp
import discord
from urllib.parse import quote_plus
from bs4 import BeautifulSoup
from html2text import html2text as h2t
from redbot.core import commands
from redbot.core.bot import Red
from redbot.core.utils.menus import SimpleMenu
from .utils import get_card, nsfwcheck, s
from .yandex import Yandex

GOOGLE_ICON = "https://lh3.googleusercontent.com/COxitqgJr1sJnIDe8-jiKhxDx1FrYbtRHKJ9z_hELisAlapwE9LUPh6fcXIfb5vwpbMl4xl9H9TRFPc5NOO8Sb3VSgIBrfRYvW6cUA"


class Google(Yandex, commands.Cog):
    """
    A Simple google search with image support as well
    """

    __version__ = "0.0.4"
    __authors__ = ["epic guy", "ow0x", "fixator10"]

    def __init__(self, bot: Red) -> None:
        super().__init__()
        self.bot = bot
        self.options = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.127 Safari/537.36",
            "accept-language": "en-GB,en-US;q=0.9,en;q=0.8",
        }
        self.link_regex = re.compile(
            r"https?:\/\/(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b(?:[-a-zA-Z0-9()@:%_\+.~#?&\/\/=]*(?:\.png|\.jpe?g|\.gif))"
        )
        self.session = aiohttp.ClientSession()

    def cog_unload(self):
        asyncio.create_task(self.session.close())

    def format_help_for_context(self, ctx: commands.Context) -> str:
        """Thanks Sinbad!"""
        pre_processed = super().format_help_for_context(ctx)
        authors = "Authors: " + ", ".join(self.__authors__)
        return f"{pre_processed}\n\n{authors}\nCog Version: {self.__version__}"

    @commands.hybrid_command()
    @commands.bot_has_permissions(embed_links=True, add_reactions=True)
    async def google(self, ctx, *, search: str):
        """Search anything on Google."""
        if not search:
            return await ctx.send("Please enter something to search")

        isnsfw = nsfwcheck(ctx)
        async with ctx.typing():
            response, kwargs = await self.get_result(search, nsfw=isnsfw)
            pages = []
            groups = [response[n : n + 1] for n in range(0, len(response), 1)]
            for num, group in enumerate(groups, 1):
                emb = discord.Embed(
                    color=await ctx.embed_color(),
                    url=kwargs["redir"])
                emb.set_author(
                    name="Google Search: " + (search[:44] + "\N{HORIZONTAL ELLIPSIS}" if len(search) > 45 else search),
                    icon_url=GOOGLE_ICON)
                for result in group:
                    desc = (f"[{result.url[:60]}]({result.url})\n" if result.url else "") + f"{result.desc}"[:800]
                    emb.add_field(
                        name=f"{result.title}",
                        value=desc or "Nothing",
                        inline=False,
                    )
                emb.set_footer(text=f"Page {num+1}/{len(groups)} | Safe Search: {not isnsfw}")
                if "thumbnail" in kwargs:
                    emb.set_thumbnail(url=kwargs["thumbnail"])

                if "image" in kwargs and num == 1:
                    emb.set_image(url=kwargs["image"])
                pages.append(emb)
        if pages:
            await SimpleMenu(pages, timeout=600).start(ctx)
        else:
            await ctx.send("No results.")

    @commands.hybrid_command(aliases=["img"])
    async def googleimage(self, ctx, *, search: str):
        """Search images on Google."""
        if not search:
            return await ctx.send("Please enter some image name to search")
        isnsfw = nsfwcheck(ctx)
        pages = []
        async with ctx.typing():
            response, kwargs = await self.get_result(search, images=True, nsfw=isnsfw)
            size = len(response)
            for i, result in enumerate(response):
                embed = discord.Embed(
                    color=await ctx.embed_color(),
                    description=f"Some images may not be visible.",
                    url=kwargs["redir"])
                embed.set_author(name="Google Images", icon_url=GOOGLE_ICON)
                embed.set_image(url=result)
                embed.set_footer(text=f"Page {i+1}/{size} | Safe Search: {'Off' if isnsfw else 'On'}")
                pages.append(embed)
            if size > 0:
                await SimpleMenu(pages, timeout=600).start(ctx)
            else:
                await ctx.send("No result")

    @commands.hybrid_command()
    async def googleautofill(self, ctx, *, search: str):
        """Responds with a list of Google autofill results."""

        params = {"client": "firefox", "hl": "en", "q": search}
        async with ctx.typing():
            # This “API” is a bit of a hack; it was only meant for use by
            # Google’s own products. and hence it is undocumented.
            # Attribution: https://shreyaschand.com/blog/2013/01/03/google-autocomplete-api/
            base_url = "https://suggestqueries.google.com/complete/search"
            try:
                async with self.session.get(base_url, params=params) as response:
                    if response.status != 200:
                        return await ctx.send(f"https://http.cat/{response.status}")
                    data = json.loads(await response.read())
            except asyncio.TimeoutError:
                return await ctx.send("Operation timed out.")

            if not data[1]:
                return await ctx.send("Could not find any results.")

            await ctx.send("\n".join(data[1]))

    async def get_result(self, query, images=False, nsfw=False):
        """Fetch the data"""
        # TODO make this fetching a little better
        encoded = quote_plus(query, encoding="utf-8", errors="replace")

        async def get_html(url, encoded):
            async with self.session.get(url + encoded, headers=self.options) as resp:
                self.cookies = resp.cookies
                return await resp.text(), resp.url

        if not nsfw:
            encoded += "&safe=active"

        # TYSM fixator, for the non-js query url
        url = (
            "https://www.google.com/search?tbm=isch&q="
            if images
            else "https://www.google.com/search?q="
        )
        text, redir = await get_html(url, encoded)
        prep = functools.partial(self.parser_image if images else self.parser_text, text)

        fin, kwargs = await self.bot.loop.run_in_executor(None, prep)
        kwargs["redir"] = redir
        return fin, kwargs

    def parser_text(self, text, soup=None, cards: bool = True):
        """My bad logic for scraping"""
        if not soup:
            soup = BeautifulSoup(text, features="html.parser")

        final = []
        kwargs = {"stats": h2t(str(soup.find("div", id="result-stats")))}

        if cards:
            get_card(soup, final, kwargs)

        for res in soup.select("div.g.tF2Cxc"):
            if name := res.find("div", class_="yuRUbf"):
                url = name.a["href"]
                if title := name.find("h3", class_=re.compile("LC20lb")):
                    title = title.text
                else:
                    title = url
            else:
                url = None
                title = None
            if final_desc := res.select("div.VwiC3b.yXK7lf.MUxGbd"):
                desc = h2t(str(final_desc[-1]))[:500]
            else:
                desc = "Not found"
            if title:
                final.append(s(url, title, desc.replace("\n", " ")))
        return final, kwargs

    def parser_image(self, html):
        excluded_domains = (
            "google.com",
            "gstatic.com",
        )
        links = self.link_regex.findall(html)
        ind = 0
        count = 0
        while count <= 10:  # first 10 should be enough for the google icons
            for remove in excluded_domains:
                if not links:
                    return [], {}
                if remove in links[ind]:
                    links.pop(ind)
                    break
            else:
                ind += 1
            count += 1
        return links, {}
