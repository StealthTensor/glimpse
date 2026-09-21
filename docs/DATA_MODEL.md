# Data Model

Conceptual structure:

``` text
identity
  id
  username
  created_at
  updated_at

template
  identity_id
  embedding
  quality
  created_at
```

Storage requirements: - user/system ownership must be explicit; -
permissions must prevent other users from reading templates; - raw
enrollment frames should not be retained unless explicitly required; -
logs must not contain embeddings or captured images.
