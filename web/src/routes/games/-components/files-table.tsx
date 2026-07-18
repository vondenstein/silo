import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import type { ArtifactOut } from "@/lib/api/model"
import { formatSize } from "@/lib/format-size"

export function FilesTable({ artifacts }: { artifacts: ArtifactOut[] }) {
  const rows = artifacts.flatMap((artifact) => artifact.files.map((file) => ({ artifact, file })))

  return (
    <section className="space-y-3">
      <h2 className="text-lg font-semibold">Files</h2>
      {rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">No files for this game.</p>
      ) : (
        <div className="overflow-hidden rounded-lg border">
          <Table>
            <TableHeader className="bg-muted">
              <TableRow>
                <TableHead>File</TableHead>
                <TableHead className="w-32">Kind</TableHead>
                <TableHead className="w-28">Status</TableHead>
                <TableHead className="w-28 text-right">Size</TableHead>
                <TableHead className="w-28 text-right">
                  <span className="sr-only">Download</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map(({ artifact, file }) => {
                const stored = file.blake3 != null
                return (
                  <TableRow key={file.id}>
                    <TableCell className="font-mono text-xs">
                      {filename(file.relative_path) ?? artifact.name ?? "—"}
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">{artifact.kind}</TableCell>
                    <TableCell>
                      {/* Backend vocabulary; a not-yet-hashed file is "missing". */}
                      <Badge variant={stored ? "secondary" : "outline"}>
                        {stored ? "stored" : "missing"}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right text-xs text-muted-foreground tabular-nums">
                      {formatSize(file.size)}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-2">
                        {stored && isPdf(file.relative_path) && (
                          <Button variant="outline" size="sm" asChild>
                            <a
                              href={`/api/v1/files/${file.id}?inline=true`}
                              target="_blank"
                              rel="noreferrer"
                            >
                              View
                            </a>
                          </Button>
                        )}
                        {stored && (
                          <Button variant="outline" size="sm" asChild>
                            <a href={`/api/v1/files/${file.id}`}>Download</a>
                          </Button>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </div>
      )}
    </section>
  )
}

function filename(path: string | null): string | null {
  return path?.split("/").pop() ?? null
}

function isPdf(path: string | null): boolean {
  return path?.toLowerCase().endsWith(".pdf") ?? false
}
