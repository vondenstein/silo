import { IgdbCard } from "@/routes/settings/-components/metadata/igdb-card"
import { SourcesCard } from "@/routes/settings/-components/metadata/sources-card"

export function MetadataSection() {
  return (
    <>
      <SourcesCard />
      <IgdbCard />
    </>
  )
}
