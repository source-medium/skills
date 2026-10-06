# BigQuery Access Request Template

Use this when a user cannot reach SourceMedium data.

## Two Ways In

- **Through SourceMedium, on every plan**: the SourceMedium MCP, signed in with
  the user's SourceMedium account. It needs no BigQuery permissions. Agency
  (partner) access works this way too.
- **Direct warehouse access, on Pro**: the user's own Google account (or the
  customer's service accounts) querying BigQuery on the dedicated warehouse.
  Foundation plans do not include it; on Foundation, use the MCP.

## How Direct Access Is Granted (Pro)

SourceMedium grants it from membership in the customer's SourceMedium
workspace. The customer's own Google Cloud admin cannot grant it to people.

- **Who gets it**: accepted, direct members of the workspace.
- **Which identity**: the Google account whose email matches the workspace
  membership.
- **What it includes**: viewers read SourceMedium's datasets and run queries;
  editors and admins can also create their own datasets in the project; admins
  can grant the customer's own service accounts.
- **How fast**: usually within minutes of accepting the invitation.

## What To Do

1. **On Foundation, or with agency access**: connect the SourceMedium MCP to the
   agent (https://docs.sourcemedium.com/ai-analyst/connect-an-ai-assistant).
2. **On Pro, not a member yet**: ask a workspace admin (or editor) to invite
   you, using the Google account you will sign in to `gcloud` with. Accept the
   invitation.
3. **On Pro, a member, but queries fail**: confirm `gcloud auth list` shows that
   same account, wait a few minutes after accepting, then rerun
   `python scripts/sm_bq_doctor.py --project <project>`.
4. **Still failing**: send SourceMedium support the doctor output and the exact
   error.

## Copy/paste message for a workspace admin (Pro)

```text
Subject: SourceMedium workspace invitation for BigQuery analysis

Hi,

Please invite me to our SourceMedium workspace so I can query our SourceMedium
data in BigQuery:

- Google account: <your Google account email>
- Role: Viewer (or Editor if I need to create my own datasets)

SourceMedium grants BigQuery access automatically to accepted members; no
Google Cloud change is needed on our side.

Thanks.
```

## Copy/paste message for SourceMedium support

```text
Subject: BigQuery access not working

Workspace: <workspace name>
Google account: <your Google account email>
Project tried: <project>
Doctor output and exact error:
<paste here>
```

## Success Criteria

- Through the MCP: `get_data_context` returns the warehouse and its datasets.
- Directly (Pro): `python scripts/sm_bq_doctor.py --project <project>` passes
  and prints your dataset names.
