
job("Build and push Docker"){
    host("Build and push a Docker image") {
        
        dockerBuildPush {
            file = "/docker/Dockerfile"
            tags {
                // use current job run number as a tag - '0.0.run_number'
                +"lightny.registry.jetbrains.space/p/main/containers/discord-bot:latest"
            }
        }
    }
}