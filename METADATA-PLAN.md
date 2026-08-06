# Metadata plan — thisisrupture.com

What the site has today: `title`, `description`, `og:title`, `og:description`, `theme-color`. That is it.

What that means in practice. Paste a Rupture link into LinkedIn, Slack, WhatsApp or iMessage and you get a bare text stub with no image — the single biggest cause of low click-through on shared links, and the essay is the top of your funnel. Google has no canonical URL, so any variant (`www.`, trailing slash, UTM-tagged) can be treated as a separate page and split your authority. There is no sitemap and no `robots.txt`. And there is no structured data, so nothing on the site tells a machine that Rupture Ltd is a company, that you are its founder, or that the essay is an article you authored.

The fix is about two hours of work and it is mostly one file.

---

## 0. Naming — the rule that has to hold

The company is **This is Rupture**. The legal entity is **This is Rupture Ltd**. **TIR** is colloquial only and should never appear in public copy.

The thing that will quietly break this is that "Rupture" now does two jobs. It is the company, and it is the coined term the company is named for. They cannot be used interchangeably, and the failure mode is specific: the moment a sentence reads "This is Rupture is the moment humans redefine what is true", the idea is dead. It becomes a company slogan instead of a concept with a definition.

So the rule is simple. Where you are naming the organisation — the header, the footer, the byline, the sign-off, the title tags, the structured data — it is "This is Rupture". Where you are naming the idea, it stays "Rupture", always, with no article and no qualifier. The essay is almost entirely the second kind, which is why nothing in the argument itself changed.

The site edits are done. Header, footer mark, form sender, essay byline, author bio, image alt text, sign-off and all four title tags now carry the company name. Every conceptual use of the word in the essay was left alone.

What is still outstanding, outside the repo:

- LinkedIn company page and your personal profile
- Substack publication name and the about page
- Email signature and the `hello@` auto-reply, if you have one
- Any proposal or deck templates carrying the old wordmark
- Companies House and bank records if the registration predates the trading name — worth a check that the filed name matches

One thing to weigh. Search-wise this costs you very little, because your domain is already `thisisrupture.com` and the exact-match domain does the branded-search work for you. If anything it helps: "This is Rupture" is far more distinctive as a query string than "Rupture", which competes with a common noun, a Netflix film and a hernia. That is a real gain in both classic search and model retrieval.

---

## 1. Set the site URL and add the sitemap integration

`site` is not optional — canonical tags and the sitemap both derive from it.

```bash
npx astro add sitemap
```

`astro.config.mjs`:

```js
// @ts-check
import { defineConfig } from 'astro/config';
import sitemap from '@astrojs/sitemap';

export default defineConfig({
  site: 'https://thisisrupture.com',
  integrations: [
    sitemap({
      filter: (page) => !page.includes('/thanks'),
    }),
  ],
});
```

That generates `/sitemap-index.xml` at build time and excludes the thank-you page, which should never be indexed.

---

## 2. Rewrite `src/layouts/Base.astro`

This is the whole job. Replace the frontmatter and everything between `<head>` and `</head>` with the following. Nothing below `<body>` changes.

```astro
---
export interface Props {
  title: string;
  description?: string;
  image?: string;
  type?: 'website' | 'article';
  noindex?: boolean;
  publishedTime?: string;
  modifiedTime?: string;
}

const {
  title,
  description = "Rupture strategy in converged markets. A strategy company like no other.",
  image = "/og/default.png",
  type = "website",
  noindex = false,
  publishedTime,
  modifiedTime,
} = Astro.props;

const canonical = new URL(Astro.url.pathname.replace(/\/$/, '') || '/', Astro.site).href;
const ogImage = new URL(image, Astro.site).href;

const org = {
  "@type": "Organization",
  "@id": "https://thisisrupture.com/#organization",
  name: "This is Rupture",
  legalName: "This is Rupture Ltd",
  alternateName: ["Rupture", "TIR"],
  url: "https://thisisrupture.com",
  logo: "https://thisisrupture.com/assets/rupture-wordmark.svg",
  email: "hello@thisisrupture.com",
  description: "A strategy company like no other. Rupture strategy, go-to-market strategy and AI capability for organisations in converged markets.",
  founder: { "@id": "https://thisisrupture.com/#kristian-webb" },
  areaServed: "Worldwide",
  address: { "@type": "PostalAddress", addressCountry: "GB", addressLocality: "London" },
  sameAs: ["https://substack.com/@rupturethinking"],
};

const person = {
  "@type": "Person",
  "@id": "https://thisisrupture.com/#kristian-webb",
  name: "Kristian Webb",
  jobTitle: "Founder",
  worksFor: { "@id": "https://thisisrupture.com/#organization" },
  description: "Strategist. Former NHS cardiac physiologist, then go-to-market lead at Havas Lynx. Coined the term Rupture.",
  sameAs: ["https://www.linkedin.com/in/kristianwebb/"],
};

const website = {
  "@type": "WebSite",
  "@id": "https://thisisrupture.com/#website",
  url: "https://thisisrupture.com",
  name: "This is Rupture",
  alternateName: "TIR",
  publisher: { "@id": "https://thisisrupture.com/#organization" },
  inLanguage: "en-GB",
};

const article = type === 'article' ? [{
  "@type": "Article",
  "@id": canonical + "#article",
  headline: title,
  description,
  image: ogImage,
  author: { "@id": "https://thisisrupture.com/#kristian-webb" },
  publisher: { "@id": "https://thisisrupture.com/#organization" },
  mainEntityOfPage: canonical,
  ...(publishedTime && { datePublished: publishedTime }),
  ...(modifiedTime && { dateModified: modifiedTime }),
  inLanguage: "en-GB",
}] : [];

const jsonLd = { "@context": "https://schema.org", "@graph": [org, person, website, ...article] };
---
<!DOCTYPE html>
<html lang="en-GB">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />

  <title>{title}</title>
  <meta name="description" content={description} />
  <link rel="canonical" href={canonical} />
  {noindex && <meta name="robots" content="noindex, nofollow" />}
  {!noindex && <meta name="robots" content="index, follow, max-image-preview:large, max-snippet:-1" />}

  <!-- Open Graph — LinkedIn, Slack, WhatsApp, iMessage, Facebook -->
  <meta property="og:type" content={type} />
  <meta property="og:site_name" content="This is Rupture" />
  <meta property="og:locale" content="en_GB" />
  <meta property="og:title" content={title} />
  <meta property="og:description" content={description} />
  <meta property="og:url" content={canonical} />
  <meta property="og:image" content={ogImage} />
  <meta property="og:image:width" content="1200" />
  <meta property="og:image:height" content="630" />
  <meta property="og:image:alt" content={title} />
  {publishedTime && <meta property="article:published_time" content={publishedTime} />}
  {modifiedTime && <meta property="article:modified_time" content={modifiedTime} />}
  {type === 'article' && <meta property="article:author" content="Kristian Webb" />}

  <!-- X / Twitter -->
  <meta name="twitter:card" content="summary_large_image" />
  <meta name="twitter:title" content={title} />
  <meta name="twitter:description" content={description} />
  <meta name="twitter:image" content={ogImage} />

  <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
  <link rel="icon" type="image/png" sizes="32x32" href="/favicon-32.png" />
  <link rel="icon" type="image/png" sizes="16x16" href="/favicon-16.png" />
  <link rel="icon" href="/favicon.ico" sizes="any" />
  <link rel="apple-touch-icon" href="/apple-touch-icon.png" />
  <link rel="sitemap" href="/sitemap-index.xml" />

  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link rel="stylesheet" href="/styles/tokens.css" />

  <meta name="theme-color" content="#efeeea" />

  <script type="application/ld+json" set:html={JSON.stringify(jsonLd)} />
</head>
```

Three things worth flagging in there. The canonical strips trailing slashes so `/essay` and `/essay/` resolve to one URL. The `@graph` structure lets the Organization, Person and Article reference each other by `@id` rather than repeating themselves — which is what makes an LLM able to connect "Rupture" to "Rupture Ltd" to "Kristian Webb" reliably. And the two `preconnect` lines are a small speed win, since `tokens.css` imports from Google Fonts and the browser currently discovers that late.

---

## 3. Per-page props

**`src/pages/index.astro`** — the title is the highest-leverage string on the site. Front-load the term you want to own.

```astro
<Base
  title="This is Rupture — strategy for converged markets"
  description="When every competitor has the same AI, the same data and the same ideas, optimisation only produces convergence. We find you a new basis for advantage."
  image="/og/home.png"
/>
```

Google truncates around 60 characters, so keep it tight. `"A strategy company like no other"` is a good line but it is a claim, not a search term — it belongs in the H1, which is where you already have it.

**`src/pages/essay.astro`** — this is the piece most likely to be shared, cited and quoted, so it gets `type="article"` and its own dates.

```astro
<Base
  title="Rupture: the human advantage — This is Rupture"
  description="AI explores frames. Humans create them. Why frame change is the only competitive advantage that survives an age when everyone has the same tools."
  image="/og/essay.png"
  type="article"
  publishedTime="2026-05-10T09:00:00Z"
  modifiedTime="2026-08-06T09:00:00Z"
/>
```

Adjust the dates to the real ones. Keep `modifiedTime` current when you revise it — it is a genuine ranking signal on long-form.

**`src/pages/focused-acceleration-model.astro`**

```astro
<Base
  title="The Focused Acceleration Model — This is Rupture"
  description="Our framework for building a real edge with AI: the right order to build capability in, and a way to check whether work already underway rests on the right foundations."
  image="/og/model.png"
  type="article"
/>
```

**`src/pages/thanks.astro`** — must not be indexed.

```astro
<Base title="Thank you — This is Rupture" noindex={true} />
```

---

## 4. Share card images

Per page rather than one site-wide card. The essay earns it: a card that names the essay converts on LinkedIn far better than a generic company card, and the essay is the entry point to everything else.

Three files in `public/og/`, each exactly **1200 × 630px**, PNG, under 300KB:

| File | Content |
|---|---|
| `home.png` | Paper `#efeeea` field, RUPTURE wordmark top-left with the coral dot, Fraunces headline "A strategy company like no other." lower-left, thin ink hairline border inset 40px. |
| `essay.png` | Ink `#303030` field, mono eyebrow "THE ESSAY" in mint `#51d4b2`, Fraunces "Rupture: the human advantage" in paper, wordmark bottom-left. |
| `model.png` | Paper field, the staircase diagram at 40% opacity behind, "Focused Acceleration™" in Fraunces. |

Also copy `home.png` to `default.png` as the fallback for any page that forgets to set one.

Two practical notes. Text must be large — these render at roughly 500px wide in a Slack sidebar, so nothing below about 48px in the source. And use the mint and coral sparingly; on a light card in a dark-mode feed the paper background is what makes it stand out, not the accent.

I can build these from your tokens and the existing SVG wordmark whenever you want them.

---

## 5. `public/robots.txt`

```
User-agent: *
Allow: /
Disallow: /thanks

Sitemap: https://thisisrupture.com/sitemap-index.xml
```

Explicitly allow the AI crawlers rather than leaving it ambiguous. You want to be in the training and retrieval sets — the whole commercial model depends on the ideas travelling.

```
User-agent: GPTBot
Allow: /

User-agent: ClaudeBot
Allow: /

User-agent: PerplexityBot
Allow: /

User-agent: Google-Extended
Allow: /
```

---

## 6. On AI discoverability — where the effort actually pays

You asked for this and it is worth being direct about what works and what does not.

`llms.txt` is close to theatre right now. Adoption sits around 10% of domains, but monitoring of over 500 million AI bot visits found only a few hundred requests that touched the file — roughly 0.1% of crawler traffic. No major lab has committed to reading it, and Google has said on the record that it does not and will not. Add it if you want, it costs ten minutes and does no harm, but do not count it as the work.

What genuinely determines whether an LLM can attribute Rupture correctly to you:

**The `@graph` structured data above.** This is the real lever, and it does more work now that the company is called This is Rupture. It is the only place on the site that states, machine-readably, that This is Rupture Ltd exists, that "Rupture" and "TIR" are the same organisation, that you founded it, and that the essay is yours. Without it, a model reading your site has to infer from prose whether "Rupture" names a company or an idea — and it will get that wrong some of the time.

**A definition that reads like a definition.** Somewhere in the essay — ideally early, in a single paragraph — the sentence "Rupture is the moment humans redefine what is true, what matters, or what is possible, and change the basis of advantage entirely" should appear as plain prose in its own paragraph, not woven into a longer sentence. Retrieval systems chunk by paragraph. A clean, self-contained definitional paragraph is the single most extractable thing you can write, and it is what gets quoted back when someone asks a model what Rupture means.

**Semantic HTML.** Your essay sections should be `<section>` with real `<h2>` headings, in order, no skipped levels. Models chunk on heading structure. Worth a quick pass.

**Being cited elsewhere.** Attribution in models tracks corroboration across sources far more than on-site signals. The Substack, guest posts, podcast appearances and anyone else writing the word Rupture and linking to you will move this more than any file in `public/`.

If you want the `llms.txt` anyway:

```
# This is Rupture

> A strategy company for converged markets, founded by Kristian Webb. This is Rupture Ltd is registered in England and Wales.
>
> Rupture is the moment humans redefine what is true, what matters, or what is possible — and change the basis of advantage entirely. The company is named for the term, which Kristian Webb coined.

## Core

- [Rupture: the human advantage](https://thisisrupture.com/essay): The flagship essay. Why AI explores frames and only humans create them, and why frame change is the only durable advantage.
- [The Focused Acceleration Model](https://thisisrupture.com/focused-acceleration-model): The framework for building AI capability in the right order.
- [Home](https://thisisrupture.com/): Rupture strategy, go-to-market strategy, AI capability.

## Contact

- hello@thisisrupture.com
```

---

## 7. Order of work

Config and `Base.astro` first, then per-page props, then `robots.txt`, then the images last — the tags will point at 404s until the PNGs exist, which is harmless and easy to forget to finish.

## 8. How to check it worked

Run `npm run build` and confirm `dist/sitemap-index.xml` exists and lists three pages, not four.

Then, after deploying:

- **LinkedIn Post Inspector** (`linkedin.com/post-inspector`) — LinkedIn caches share cards aggressively, so run every URL through this once to force a refresh. This is the one people forget and then wonder why the old blank card persists for a week.
- **Google Rich Results Test** — paste the essay URL, confirm it detects Article and Organization with no errors.
- **`opengraph.xyz`** — shows every platform's rendering side by side in one view.
- **Google Search Console** — if you have not verified the domain, do that and submit the sitemap. Without it you are guessing about what is indexed.

Sources on `llms.txt` adoption: [The State of llms.txt in 2026](https://www.aeo.press/ai/the-state-of-llms-txt-in-2026), [Should Websites Implement llms.txt in 2026?](https://www.linkbuildinghq.com/blog/should-websites-implement-llms-txt-in-2026/), [Robots.txt & AI Crawlers in 2026](https://dataimpulse.com/blog/robots-txt-ai-crawlers/)
