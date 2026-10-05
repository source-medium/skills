# Before we validate: what you need in place

Your assistant is about to check a SourceMedium number against the source
platform's own records, order by order. To do that it needs a few things
from you up front. Nothing on this list involves sharing a password, an
authenticator code, or an API key with the assistant; it works through
access you already have.

## 1. The number you are questioning

- Which metric (net sales, gross sales, order count, refunds).
- Where it came from: the exact report or dashboard on each side, and any
  filter it had (for example, point-of-sale excluded).
- The date range, start and end, inclusive.
- Which store, if your business runs more than one.
- The two figures as you see them.
- Your Shopify store's timezone (Shopify admin → Settings → General →
  Standards and formats). It decides which day each order lands on.

## 2. Your SourceMedium warehouse

- Your SourceMedium project id. It usually looks like `sm-<yourbrand>`.
- A Google account with read access to that project: `BigQuery Job User` on
  the project and `BigQuery Data Viewer` on the `sm_transformed_v2` and
  `sm_metadata` datasets. If you are not sure you have it, the assistant can
  give you a request to send to whoever administers your Google Cloud.
- The Google Cloud command-line tools (`gcloud` and `bq`) installed and
  signed in on the machine the assistant runs on. The assistant can walk
  you through this.
- Python 3.9 or newer on that machine, for the comparison script.

## 3. A way to get Shopify's own numbers

Pick whichever applies; the assistant tries them in this order.

**A. Your Shopify orders already land in your own BigQuery tables**
(through a connector you run, or SourceMedium raw data delivery).

- The project, dataset, and table name.
- Read access to it for the same Google account as above.

**B. The assistant can use a browser you are signed into**

- A browser the assistant is allowed to drive (for example, Claude in
  Chrome with permission for `admin.shopify.com`), on a machine where you
  are already signed in to Shopify admin for the right store.
- Your Shopify staff account needs the **Reports** permission (store
  owners have it; for staff it is under Analytics in their permissions).
  It covers creating and exporting explorations. Explorations exist on
  every Shopify plan, so there is nothing to check on the plan.
- Your two-step authentication device within reach. Shopify may ask for a
  code when the admin opens; you type it, the assistant waits.
- Know where that browser saves downloads. The export is a CSV file.
- Stay reachable while it runs. It takes a few minutes.

**C. You export a CSV yourself and share it**

- For the preferred export (Analytics exploration): the same **Reports**
  permission as above.
- For the fallback export (Orders page): the **Orders** permission and its
  separate **Export** permission, plus access to the email inbox Shopify
  sends date-range exports to (yours and the store owner's).
- A way to hand the file to the assistant.

## 4. Two decisions

- How close is close enough? The assistant proposes a per-order tolerance
  of 0.01 and a total tolerance of 1.00 in your store currency unless you
  say otherwise. Order counts are compared exactly.
- Who should receive the report, and in what form.

## What the assistant will never ask you for

Your Shopify password, your authenticator codes, API tokens or access
keys, or customer names, emails, and addresses. If anything you are handed
asks for those, stop and check with SourceMedium support.

## You are ready when

- The number, report, window, store, and timezone are written down.
- A quick test query against your SourceMedium project succeeds.
- You know which of A, B, or C you will use and have what it needs.
