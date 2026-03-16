# company-profile-lite

Extract a clean company profile from a website URL.

## What it does

Give it a company website URL and it returns a simple JSON profile with useful public business info such as:

- company name
- short description
- email addresses
- phone numbers
- social links
- likely location mentions

## Why this exists

This is a lightweight, useful community agent that can later grow into richer enrichment agents.

## Example input

{
  "company_name": "Example Inc.",
  "description": "Example provides software for modern teams.",
  "emails": ["hello@example.com"],
  "phones": ["+1 555 123 4567"],
  "socials": {
    "linkedin": "https://linkedin.com/company/example",
    "twitter": "https://twitter.com/example"
  },
  "locations": ["New York, USA"]
}


