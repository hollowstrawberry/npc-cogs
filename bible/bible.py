import re
import aiohttp
import bs4
import discord
from html2text import html2text as h2t
from redbot.core import commands
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import pagify
from redbot.core.utils.menus import SimpleMenu

from .utils import EmbedField, group_embed_fields


class Bible(commands.Cog):
    """
    Pull up biblical verses fast
    """

    def __init__(self, bot: Red):
        super().__init__()
        self.bot = bot
        self.BASE_URL = "https://www.biblegateway.com"
        self.ver_re = re.compile(r"--?(?:V|v|ver|version)(?:=| )(\w+)")

    async def red_delete_data_for_user(self, *, requester, user_id: int) -> None:
        return

    def parse_search(self, text, title, version, emb_color):
        fields = []
        pages = []
        for result in text.findAll("li", {"class": "bible-item"}):
            ref = result.find("a", {"class": "bible-item-title"})
            name = ref.text
            value = result.find("div", {"class": "bible-item-text"})
            value.find("div").decompose()
            # Change headers to markdown
            for h3 in value.find_all("h3"):
                h3.name = "b"
            fields.append(
                EmbedField(
                    name, f"[{h2t(str(value))}]({self.BASE_URL+ref.get('href')})"[:1000], False
                )
            )

        raw = group_embed_fields(fields)
        size = len(raw)
        for i, group in enumerate(raw, 1):
            emb = discord.Embed(title="Search Results for " + title, colour=emb_color)
            emb.set_footer(
                text=f"Version: {version} | Powered by Biblegateway.com | Page {i}/{size}"
            )
            for field in group:
                emb.add_field(**field._asdict())
            pages.append(emb)

        return pages

    def parse_reference(self, text, full_chap, title, version, emb_color):
        # Remove cross references
        for sup in text.find_all("sup", {"class": "crossreference"}):
            sup.decompose()

        # Remove other hidden junk
        for div_class in ("footnotes", "crossrefs", "passage-other-trans", "full-chap-link"):
            if elements := text.find_all(class_=div_class):
                for ele in elements:
                    if isinstance(ele, bs4.Tag):
                        ele.decompose()

        # Change headers to markdown
        for h3 in text.find_all("h3"):
            h3.name = "b"
        for h4 in text.find_all("h4"):
            h4.name = "b"

        text = h2t(str(text))
        pages = []
        raw = list(pagify(text, page_length=4000))
        size = len(raw)

        for i, page in enumerate(raw, 1):
            emb = discord.Embed(title=title, description=page, colour=emb_color)
            emb.url = full_chap
            emb.set_footer(
                text=f"Version: {version} | Powered by Biblegateway.com | Page {i}/{size}"
            )
            pages.append(emb)
        return pages

    @commands.hybrid_command()
    async def bible(self, ctx, *, verses):
        """
        Pull up bible verses or reverse search by querying a word and get all it's references

        Now supports version as well, look up to this site for available versions: https://www.biblegateway.com/versions

        Example:
        [p]bible revelation 1:1
        [p]bible gen 1:1 -v KJV
        [p]bible gen1:5 --version NKJV
        [p]bible test
        """
        version = "NIV"
        if ver_match := self.ver_re.search(verses):
            version = ver_match.group(1)
            verses = self.ver_re.sub("", verses).strip()

        if re.match(r"\w+(?: ?)\d+:\d+", verses):
            url = "/passage/?search="
        else:
            url = "/quicksearch/?quicksearch="

        async with ctx.typing():
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self.BASE_URL + url + verses + f"&version={version}"
                ) as resp:
                    soup = bs4.BeautifulSoup(await resp.text(), "html.parser")

                # Reference search
                if text := soup.find("div", {"class": "passage-text"}):
                    full_chap = soup.find("a", {"class": "full-chap-link"})
                    title = soup.find("div", {"class": "dropdown-display-text"}).text
                    pages = self.parse_reference(
                        text,
                        (self.BASE_URL + full_chap.get("href")) if full_chap else None,
                        title,
                        version,
                        emb_color=await ctx.embed_color(),
                    )

                # Word Search
                elif text := soup.find("div", {"class": "search-result-list"}):
                    pages = self.parse_search(
                        text, verses, version, emb_color=await ctx.embed_color()
                    )
                # No result checks
                else:
                    return await ctx.send(
                        "**No results found**\n"
                        "1) Kindly make sure the verse exists\n"
                        "2) Use the format of `book chapter:verse-range`"
                    )
            if len(pages) > 1:
                await SimpleMenu(pages, timeout=600).start(ctx)
            else:
                await ctx.send(embed=pages[0])
