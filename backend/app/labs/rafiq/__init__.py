"""RAFIQ LAB — a collaborator's five strategies, run beside the existing engines.

Isolated by construction, not by convention:

* its own tables (`rafiq_lab_*`), its own $1,000 book, its own feature flag;
* it reads the shared token feed through `feed.RafiqFeed` and writes nothing
  back to it;
* it imports no paper, karthik, real-wallet or lab engine. A test parses this
  package's source and fails if that ever stops being true.

Nothing here touches a chain. A position is a row recording what a published
rule would have done.
"""
