var builder = DistributedApplication.CreateBuilder(args);

var pgadminEmail = builder.AddParameter("pgadmin-email", secret: true)
    .WithDescription("pgAdmin email address");
var pgadminPassword = builder.AddParameter("pgadmin-password", secret: true)
    .WithDescription("pgAdmin password");

var kafka = builder.AddKafka("kafka")
    .WithKafkaUI(kafkaUI => kafkaUI.WithHostPort(9100))
    .WithDataVolume()
    .WithLifetime(ContainerLifetime.Persistent)
    .WithContainerName("wyb-kafka");

builder.AddDockerComposeEnvironment("wyb")
       .WithDashboard(db => db.WithHostPort(8085))
       .ConfigureComposeFile(file =>
       {
           file.Name = "wyb";
       });

var postgres = builder.AddPostgres("postgres", port: 5433)
    .WithDataVolume()
    .WithLifetime(ContainerLifetime.Persistent)
    .WithContainerName("wyb-postgres")
    .WithPgWeb(containerName: "wyb-pgweb", configureContainer: pgWeb =>
    {
        pgWeb.WithHostPort(8080);
    });

var ledgerDb = postgres.AddDatabase("ledger-db");

// .NET service: ledger
var ledger = builder.AddProject<Projects.Wyb_Ledger>("ledger")
    .WithEndpoint("http", e => e.Port = 5100)
    .WithReference(kafka)
    .WaitFor(kafka)
    .WithReference(ledgerDb)
    .WaitFor(ledgerDb);

// Go service: ingest
var ingest = builder.AddGolangApp("ingest", "../services/ingest")
    .WithHttpEndpoint(port: 5200, env: "PORT")
    .WithOtlpExporter()
    .WithReference(kafka)
    .WaitFor(kafka)
    .WithEnvironment("DROP_DIR", "../../data/drop")
    .WithEnvironment("RAW_DIR", "../../data/raw");

// Python services
var rulesDb = postgres.AddDatabase("rules-db");

var rules = builder.AddUvicornApp("rules", "../services/rules", "rules.main:app")
    .WithUv()
    .WithHttpEndpoint(port: 5300, env: "PORT")
    .WithReference(rulesDb)
    .WaitFor(rulesDb)
    .WithEnvironment("PYTHONUNBUFFERED", "1");

var categorize = builder.AddUvicornApp("categorize", "../services/categorize", "categorize.main:app")
    .WithUv()
    .WithHttpEndpoint(port: 5400, env: "PORT")
    .WithOtlpExporter()
    .WithReference(kafka)
    .WaitFor(kafka)
    .WithReference(rules)
    .WaitFor(rules)
    .WithEnvironment("PYTHONUNBUFFERED", "1");

var detectDb = postgres.AddDatabase("detect-db");

builder.AddUvicornApp("detect", "../services/detect", "detect.main:app")
    .WithUv()
    .WithHttpEndpoint(port: 5500, env: "PORT")
    .WithOtlpExporter()
    .WithReference(kafka)
    .WaitFor(kafka)
    .WithReference(detectDb)
    .WaitFor(detectDb)
    .WithReference(ledger)
    .WaitFor(ledger)
    .WithEnvironment("PYTHONUNBUFFERED", "1");

// SvelteKit frontend
builder.AddViteApp("web", "../services/web")
    .WithEndpoint("http", e => e.Port = 5173)
    .WithReference(ledger)
    .WithReference(rules)
    .WaitFor(ledger)
    .WithEnvironment("NODE_OPTIONS", "--import ./otel.js");


builder.Build().Run();