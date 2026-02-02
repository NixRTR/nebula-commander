export interface Network {
  id: number;
  name: string;
  subnet_cidr: string;
  ca_cert_path: string | null;
  created_at: string;
}

export interface NetworkCreate {
  name: string;
  subnet_cidr: string;
}
