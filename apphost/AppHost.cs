var builder = DistributedApplication.CreateBuilder(args);

// Infrastructure
var postgres = builder.AddPostgres("postgres")
    // .WithDataVolume() // TODO: when ready, add a volume for Postgres data to ensure durability
    .WithLifetime(ContainerLifetime.Persistent)
    .WithPgAdmin();

var ledgerDb = postgres.AddDatabase("ledger-db");

var rabbit = builder.AddRabbitMQ("rabbit")
    .WithManagementPlugin()
    // .WithDataVolume() // TODO: when ready, add a volume for RabbitMQ data to ensure durability
    .WithLifetime(ContainerLifetime.Persistent);

// .NET service: ledger
var ledger = builder.AddProject<Projects.Wyb_Ledger>("ledger")
    .WithReference(ledgerDb)
    .WithReference(rabbit)
    .WaitFor(ledgerDb)
    .WaitFor(rabbit);

// Go service: ingest
var ingest = builder.AddGolangApp("ingest", "../services/ingest")
    .WithHttpEndpoint(env: "PORT")
    .WithReference(rabbit)
    .WaitFor(rabbit)
    .WithEnvironment("DROP_DIR", "../../drop")
    .WithEnvironment("RAW_DIR", "../../raw");

// Python services
builder.AddUvicornApp("categorize", "../services/categorize", "categorize.main:app")
    .WithUv()
    .WithReference(rabbit)
    .WaitFor(rabbit);

builder.AddUvicornApp("detect", "../services/detect", "detect.main:app")
    .WithUv()
    .WithReference(rabbit)
    .WaitFor(rabbit);

// SvelteKit frontend
builder.AddViteApp("web", "../services/web")
    .WithReference(ledger)
    .WaitFor(ledger)
    .WithEnvironment("NODE_OPTIONS", "--import ./otel.js");


builder.Build().Run();